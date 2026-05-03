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
    build_vector_kwargs = {}
    chat_kwargs = {}
    mllm_kwargs = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def visual_predict(self, input, **kwargs):
        self.visual_kwargs = kwargs
        return list(self.visual_results)

    def build_vector(self, visual_info):
        type(self).build_vector_kwargs = {}
        return {"vector": len(visual_info)}

    def chat(self, key_list, visual_info, vector_info=None, mllm_predict_info=None):
        type(self).chat_kwargs = {}
        return {"chat_res": dict(self.chat_res)}

    def mllm_pred(self, input, key_list):
        type(self).mllm_called = True
        type(self).mllm_kwargs = {}
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
        _FakePPChatOCRv4Doc.build_vector_kwargs = {}
        _FakePPChatOCRv4Doc.chat_kwargs = {}
        _FakePPChatOCRv4Doc.mllm_kwargs = {}
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

    def _run(self, file_path="demo.png"):
        with patch.dict(os.environ, self.env, clear=False), patch.dict(sys.modules, {"paddleocr": self.fake_module}):
            return run_pp_chatocr_v4_extraction(file_path, key_list=["Candidate Name", "Document ID"])

    def test_chat_res_becomes_field_candidates_and_mllm_runs(self):
        payload = self._run("demo.png")
        self.assertEqual(payload["field_candidates"][0]["label"], "Candidate Name")
        self.assertEqual(payload["field_candidates"][0]["extracted_value"], "Asha Rao")
        self.assertNotIn("mllm_pred_skipped_pdf_unsupported", payload["warnings"])
        self.assertTrue(_FakePPChatOCRv4Doc.mllm_called)

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

    def test_source_dimensions_survive_pp_outputs(self):
        with patch("extraction.ocr.pp_chatocr_v4._image_size", return_value=(900, 1200)):
            payload = self._run("demo.png")
        self.assertEqual(payload["spatial_text_map"][0]["source_width"], 900)
        self.assertEqual(payload["spatial_text_map"][0]["source_height"], 1200)
        self.assertEqual(payload["field_candidates"][0]["source_width"], 900)

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


class _FakePPChatOCRv4DocWithConfigs(_FakePPChatOCRv4Doc):
    def build_vector(self, visual_info, retriever_config=None):
        type(self).build_vector_kwargs = {"retriever_config": retriever_config}
        return {"vector": len(visual_info)}

    def chat(self, key_list, visual_info, vector_info=None, mllm_predict_info=None, chat_bot_config=None):
        type(self).chat_kwargs = {"chat_bot_config": chat_bot_config}
        return {"chat_res": dict(self.chat_res)}

    def mllm_pred(self, input, key_list, mllm_chat_bot_config=None):
        type(self).mllm_called = True
        type(self).mllm_kwargs = {"mllm_chat_bot_config": mllm_chat_bot_config}
        return {"mllm_res": dict(self.mllm_res)}


class PPChatOCRv4AdvancedConfigTests(unittest.TestCase):
    def test_advanced_configs_are_passed_only_when_supported(self):
        env = {
            "SECUURA_OCR_ENGINE": "pp_chatocr_v4",
            "SECUURA_ENABLE_ADVANCED_PADDLE_OCR": "true",
            "PP_CHAT_OCR_PIPELINE": "PP-ChatOCRv4-doc",
            "PP_CHAT_OCR_DEVICE": "cpu",
            "PP_CHAT_OCR_ENABLE_TABLE_RECOGNITION": "true",
            "PP_CHAT_OCR_ENABLE_SEAL_RECOGNITION": "true",
            "PP_CHAT_OCR_ENABLE_DOC_ORIENTATION": "true",
            "PP_CHAT_OCR_ENABLE_DOC_UNWARPING": "true",
            "PP_CHAT_OCR_CHAT_API_KEY": "chat-key",
            "PP_CHAT_OCR_CHAT_BASE_URL": "https://chat.example",
            "PP_CHAT_OCR_CHAT_MODEL_NAME": "chat-model",
            "PP_CHAT_OCR_RETRIEVER_API_KEY": "retriever-key",
            "PP_CHAT_OCR_RETRIEVER_BASE_URL": "https://retriever.example",
            "PP_CHAT_OCR_RETRIEVER_MODEL_NAME": "retriever-model",
            "PP_CHAT_OCR_MLLM_API_KEY": "mllm-key",
            "PP_CHAT_OCR_MLLM_BASE_URL": "https://mllm.example",
            "PP_CHAT_OCR_MLLM_MODEL_NAME": "mllm-model",
        }
        _FakePPChatOCRv4DocWithConfigs.visual_results = [_visual_result()]
        _FakePPChatOCRv4DocWithConfigs.chat_res = {"Candidate Name": "Asha Rao"}
        fake_module = types.SimpleNamespace(PPChatOCRv4Doc=_FakePPChatOCRv4DocWithConfigs)

        with patch.dict(os.environ, env, clear=False), patch.dict(sys.modules, {"paddleocr": fake_module}):
            run_pp_chatocr_v4_extraction("demo.png", key_list=["all visible key-value pairs"])

        self.assertEqual(_FakePPChatOCRv4DocWithConfigs.build_vector_kwargs["retriever_config"]["api_key"], "retriever-key")
        self.assertEqual(_FakePPChatOCRv4DocWithConfigs.chat_kwargs["chat_bot_config"]["model_name"], "chat-model")
        self.assertEqual(_FakePPChatOCRv4DocWithConfigs.mllm_kwargs["mllm_chat_bot_config"]["base_url"], "https://mllm.example")

    def test_pdf_uses_rasterized_page_images_for_mllm(self):
        env = {
            "SECUURA_OCR_ENGINE": "pp_chatocr_v4",
            "SECUURA_ENABLE_ADVANCED_PADDLE_OCR": "true",
            "PP_CHAT_OCR_PIPELINE": "PP-ChatOCRv4-doc",
            "PP_CHAT_OCR_DEVICE": "cpu",
            "PP_CHAT_OCR_ENABLE_TABLE_RECOGNITION": "true",
            "PP_CHAT_OCR_ENABLE_SEAL_RECOGNITION": "true",
            "PP_CHAT_OCR_ENABLE_DOC_ORIENTATION": "true",
            "PP_CHAT_OCR_ENABLE_DOC_UNWARPING": "true",
        }
        _FakePPChatOCRv4Doc.visual_results = [_visual_result()]
        _FakePPChatOCRv4Doc.chat_res = {}
        _FakePPChatOCRv4Doc.mllm_res = {"Document ID": "PDF-1"}
        fake_inputs = [
            {"path": "page-1.png", "page_number": 1, "source_width": 1000, "source_height": 1400}
        ]

        class _Prepared:
            def __enter__(self):
                return fake_inputs

            def __exit__(self, exc_type, exc, tb):
                return None

        with (
            patch.dict(os.environ, env, clear=False),
            patch.dict(sys.modules, {"paddleocr": types.SimpleNamespace(PPChatOCRv4Doc=_FakePPChatOCRv4Doc)}),
            patch("extraction.ocr.pp_chatocr_v4._prepare_pp_inputs", return_value=_Prepared()),
        ):
            payload = run_pp_chatocr_v4_extraction("demo.pdf", key_list=["all document identifiers"])

        self.assertTrue(_FakePPChatOCRv4Doc.mllm_called)
        self.assertNotIn("mllm_pred_skipped_pdf_unsupported", payload["warnings"])
        self.assertEqual(payload["spatial_text_map"][0]["source_width"], 1000)


if __name__ == "__main__":
    unittest.main()
