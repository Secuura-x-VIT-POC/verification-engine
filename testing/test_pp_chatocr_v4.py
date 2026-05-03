import os
import sys
import types
import unittest
from unittest.mock import patch


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from extraction.ocr.pp_chatocr_v4 import (
    PPChatOCRConfigurationError,
    run_pp_chatocr_v4_extraction,
)


class _FakePPChatOCRv4Doc:
    visual_results = []
    chat_res = {}
    mllm_res = {}
    mllm_called = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def visual_predict(self, input, **kwargs):
        self.visual_kwargs = kwargs
        return list(self.visual_results)

    def build_vector(self, visual_info):
        return {"vector": len(visual_info)}

    def chat(self, key_list, visual_info, vector_info=None, mllm_predict_info=None):
        return {"chat_res": dict(self.chat_res)}

    def mllm_pred(self, input, key_list):
        type(self).mllm_called = True
        return {"mllm_res": dict(self.mllm_res)}

    def close(self):
        return None


def _visual_result(*, rec_texts=None, rec_polys=None, rec_boxes=None, table_texts=None):
    table_res_list = []
    if table_texts:
        table_res_list.append(
            {
                "cell_bbox_list": [[10, 100, 100, 130]],
                "table_ocr_pred": {
                    "rec_texts": table_texts,
                    "rec_scores": [0.91 for _ in table_texts],
                    "rec_polys": [[[10, 100], [100, 100], [100, 130], [10, 130]] for _ in table_texts],
                    "rec_boxes": [[10, 100, 100, 130] for _ in table_texts],
                },
            }
        )
    return {
        "visual_info": {"normal_text_dict": {}, "table_text_list": [], "table_html_list": [], "table_nei_text_list": []},
        "layout_parsing_result": {
            "parsing_res_list": [
                {
                    "block_label": "text",
                    "block_content": "Candidate Name Asha Rao",
                    "block_bbox": [5, 5, 180, 40],
                }
            ],
            "overall_ocr_res": {
                "rec_texts": rec_texts or ["Asha", "Rao"],
                "rec_scores": [0.96, 0.94],
                "rec_polys": rec_polys
                or [
                    [[10, 10], [50, 10], [50, 25], [10, 25]],
                    [[55, 10], [90, 10], [90, 25], [55, 25]],
                ],
                "rec_boxes": rec_boxes or [[10, 10, 50, 25], [55, 10, 90, 25]],
            },
            "table_res_list": table_res_list,
        },
    }


class PPChatOCRv4NormalizationTests(unittest.TestCase):
    def setUp(self):
        _FakePPChatOCRv4Doc.visual_results = [_visual_result()]
        _FakePPChatOCRv4Doc.chat_res = {"Candidate Name": "Asha Rao"}
        _FakePPChatOCRv4Doc.mllm_res = {}
        _FakePPChatOCRv4Doc.mllm_called = False
        self.env = {
            "SECUURA_OCR_ENGINE": "pp_chatocr_v4",
            "SECUURA_ENABLE_ADVANCED_PADDLE_OCR": "true",
            "PP_CHAT_OCR_PIPELINE": "PP-ChatOCRv4-doc",
            "PP_CHAT_OCR_DEVICE": "cpu",
            "PP_CHAT_OCR_ENABLE_TABLE_RECOGNITION": "true",
            "PP_CHAT_OCR_ENABLE_SEAL_RECOGNITION": "true",
            "PP_CHAT_OCR_ENABLE_DOC_ORIENTATION": "true",
            "PP_CHAT_OCR_ENABLE_DOC_UNWARPING": "true",
        }
        self.fake_module = types.SimpleNamespace(PPChatOCRv4Doc=_FakePPChatOCRv4Doc)

    def _run(self, file_path="demo.pdf"):
        with patch.dict(os.environ, self.env, clear=False), patch.dict(sys.modules, {"paddleocr": self.fake_module}):
            return run_pp_chatocr_v4_extraction(file_path, key_list=["Candidate Name", "Document ID"])

    def test_chat_res_becomes_field_candidates_and_pdf_skips_mllm(self):
        payload = self._run("demo.pdf")
        self.assertEqual(payload["field_candidates"][0]["label"], "Candidate Name")
        self.assertEqual(payload["field_candidates"][0]["extracted_value"], "Asha Rao")
        self.assertIn("mllm_pred_skipped_pdf_unsupported", payload["warnings"])
        self.assertFalse(_FakePPChatOCRv4Doc.mllm_called)

    def test_mllm_res_becomes_field_candidates_for_non_pdf(self):
        _FakePPChatOCRv4Doc.chat_res = {}
        _FakePPChatOCRv4Doc.mllm_res = {"Document ID": "CERT-123"}
        _FakePPChatOCRv4Doc.visual_results = [_visual_result(rec_texts=["CERT-123"], rec_boxes=[[20, 20, 90, 35]])]
        payload = self._run("demo.png")
        self.assertTrue(_FakePPChatOCRv4Doc.mllm_called)
        self.assertEqual(payload["field_candidates"][0]["extracted_value"], "CERT-123")

    def test_parsing_and_ocr_outputs_create_evidence_layout_and_coordinate_map(self):
        payload = self._run()
        self.assertTrue(payload["layout_blocks"])
        self.assertTrue(payload["evidence_lines"])
        self.assertTrue(payload["spatial_text_map"])
        self.assertEqual(payload["spatial_text_map"][0]["coordinate_space"], "pp_chatocr_image_pixels")

    def test_table_ocr_outputs_create_table_cells(self):
        _FakePPChatOCRv4Doc.visual_results = [_visual_result(table_texts=["Grade A"])]
        _FakePPChatOCRv4Doc.chat_res = {"Grade": "Grade A"}
        payload = self._run()
        self.assertTrue(any(cell.get("text_preview") == "Grade A" for cell in payload["table_cells"]))

    def test_multi_token_value_combines_multiple_pp_polygons(self):
        payload = self._run()
        candidate = payload["field_candidates"][0]
        self.assertEqual(candidate["bbox"], [10.0, 10.0, 90.0, 25.0])
        self.assertEqual(len(candidate["polygon"]), 8)

    def test_unresolved_geometry_adds_warning_and_keeps_field(self):
        _FakePPChatOCRv4Doc.visual_results = [
            _visual_result(rec_texts=[], rec_polys=[], rec_boxes=[])
        ]
        _FakePPChatOCRv4Doc.chat_res = {"Document ID": "UNMATCHED-42"}
        payload = self._run()
        self.assertEqual(payload["field_candidates"][0]["extracted_value"], "UNMATCHED-42")
        self.assertIn("bbox_unresolved", payload["warnings"])

    def test_invalid_config_raises_clear_error(self):
        bad_env = dict(self.env)
        bad_env["PP_CHAT_OCR_PIPELINE"] = "wrong"
        with patch.dict(os.environ, bad_env, clear=False), patch.dict(sys.modules, {"paddleocr": self.fake_module}):
            with self.assertRaises(PPChatOCRConfigurationError):
                run_pp_chatocr_v4_extraction("demo.pdf")

    def test_gpu_device_without_gpu_runtime_raises_clear_error(self):
        bad_env = dict(self.env)
        bad_env["PP_CHAT_OCR_DEVICE"] = "gpu:0"
        with patch.dict(os.environ, bad_env, clear=False), patch.dict(sys.modules, {"paddleocr": self.fake_module}):
            with self.assertRaises(PPChatOCRConfigurationError):
                run_pp_chatocr_v4_extraction("demo.pdf")


if __name__ == "__main__":
    unittest.main()
