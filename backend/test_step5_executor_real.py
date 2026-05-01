from app.verifier_execution.executor import VerificationTaskExecutor
from app.verification_domain.contracts import VerificationTask
from app.verifier_execution.adapters import VerificationExecutionContext


def main():
    executor = VerificationTaskExecutor()

    context = VerificationExecutionContext(
        session_id="s1",
        document_type="academic_document",
        extraction_payload={},
        connector_payload={},
        trust_outcome={},
        reason_codes=[],
    )

    task = VerificationTask(
        task_id="t1",
        credential_id="c1",
        verifier_key="academic_registry",
        verifier_label="Academic Registry",
        input_payload={"name": "Kanak", "degree": "BTech"},
        provider_candidates=["local_mock"]
    )

    class DummyCredential:
        credential_id = "c1"
        category = "academic"
        label = "Degree"

        confidence = 0.9
        extracted_value = {"name": "Kanak", "degree": "BTech"}
        source = "mock"
        issuer = "VIT"

        # 🔥 ADD THESE (important)
        bounding_box = None
        page_number = 1
        raw_text = "BTech VIT"

    result = executor._execute_task(
        task=task,
        credential=DummyCredential(),
        context=context,
    )

    print(result)


if __name__ == "__main__":
    main()