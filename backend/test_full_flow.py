
from app.verifier_execution.executor import VerificationTaskExecutor
from app.verifier_execution.adapters import VerificationExecutionContext
from app.verification_domain.contracts import (
    SessionCredentialCollection,
    SessionVerificationPlan,
    VerificationTask,
    ExtractedCredential,
)


def main():
    executor = VerificationTaskExecutor()

    # -----------------------
    # CONTEXT (required)
    # -----------------------
    context = VerificationExecutionContext(
        session_id="s1",
        document_type="academic_document",
        extraction_payload={},
        connector_payload={},
        trust_outcome={},
        reason_codes=[],
    )

    # -----------------------
    # CREDENTIAL (Phase 3 simulation)
    # -----------------------
    credential = ExtractedCredential(
        credential_id="c1",
        category="academic",
        label="Degree",

        confidence=0.9,

        # 🔥 THIS is the correct field name in your schema
        value={"name": "Kanak", "degree": "BTech"},

        bounding_box=None,
        requires_verification=True,
    )

    credential_collection = SessionCredentialCollection(
        session_id="s1",
        document_type="academic_document",
        credentials=[credential],
    )

    # -----------------------
    # TASK (Phase 4 simulation)
    # IMPORTANT: verifier_key must match provider capability
    # -----------------------
    task = VerificationTask(
        task_id="t1",
        credential_id="c1",
        verifier_key="identity_db",   # matches LocalMockProvider
        verifier_label="Identity DB",
        input_payload={"name": "Kanak"},
        provider_candidates=["local_mock"],
    )

    verification_plan = SessionVerificationPlan(
        session_id="s1",
        document_type="academic_document",
        tasks=[task],
    )

    # -----------------------
    # FULL EXECUTION
    # -----------------------
    result = executor.execute_plan(
        credential_collection=credential_collection,
        verification_plan=verification_plan,
        context=context,
    )

    # -----------------------
    # OUTPUT
    # -----------------------
    print("\n=== TASK RESULTS ===")
    for r in result["task_results"]:
        print(r)

    print("\n=== CREDENTIAL BUNDLES ===")
    for b in result["credential_bundles"]:
        print(b)

    print("\n=== EXECUTION SUMMARY ===")
    print(result["execution_summary"])


if __name__ == "__main__":
    main()
