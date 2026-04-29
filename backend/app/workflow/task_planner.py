from typing import List
from backend.app.verification_domain.contracts import (
    ExtractedCredential,
    VerificationTask,
)


def build_verification_tasks(credentials: List[ExtractedCredential]) -> List[VerificationTask]:
    """
    Build generalized verification tasks from extracted credentials.

    This replaces hardcoded routing (e.g., VIT-only logic) with:
    Credential → Task → Provider Candidates → Execution
    """

    tasks: List[VerificationTask] = []

    for cred in credentials:

        # Skip if verification not required
        if not cred.requires_verification:
            continue

        # Determine claim type
        claim_type = determine_claim_type(cred)

        # Determine providers dynamically
        provider_candidates = determine_provider_candidates(claim_type)

        # Determine required fields
        required_fields = determine_required_fields(claim_type)

        # Determine assurance level
        assurance_required = determine_assurance_level(claim_type)

        # Build input payload (what verifier will receive)
        input_payload = {
            "value": cred.value,
            "normalized_value": cred.normalized_value,
            "label": cred.label,
            "category": cred.category,
        }
        selected_provider = provider_candidates[0] if provider_candidates else None
        task = VerificationTask(
            task_id=f"task_{cred.credential_id}",
            credential_id=cred.credential_id,
            claim_type=claim_type,
            provider_candidates=provider_candidates,
            required_fields=required_fields,
            assurance_required=assurance_required,
            input_payload=input_payload,
            status="PENDING",
            selected_provider=selected_provider,
            verifier_key=selected_provider,
            verifier_label=selected_provider,
        )
        tasks.append(task)

    return tasks


# -----------------------------
# 🔧 Helper Functions
# -----------------------------

def determine_claim_type(cred: ExtractedCredential) -> str:
    """
    Map extracted credential to a generalized claim type.
    """

    label = (cred.label or "").lower()
    category = (cred.category or "").lower()

    if "degree" in label or "university" in label:
        return "academic_degree"

    if "name" in label:
        return "identity"

    if "certificate" in label:
        return "certificate"

    if "id" in label or "registration" in label:
        return "identifier"

    # fallback
    return "generic_claim"


def determine_provider_candidates(claim_type: str) -> List[str]:
    """
    Decide which providers can verify this claim.
    """

    if claim_type == "academic_degree":
        return ["entra_verified_id", "local_mock_registry"]

    if claim_type == "identity":
        return ["entra_verified_id", "local_mock_registry"]

    if claim_type == "certificate":
        return ["local_mock_registry"]

    # fallback
    return ["local_mock_registry"]


def determine_required_fields(claim_type: str) -> List[str]:
    """
    Define required fields for verification.
    """

    if claim_type == "academic_degree":
        return ["holder_name", "institution", "degree", "issue_date"]

    if claim_type == "identity":
        return ["full_name", "id_number"]

    if claim_type == "certificate":
        return ["certificate_name", "issuer"]

    return ["value"]


def determine_assurance_level(claim_type: str) -> str:
    """
    Define how strict verification must be.
    """

    if claim_type == "academic_degree":
        return "HIGH"

    if claim_type == "identity":
        return "HIGH"

    if claim_type == "certificate":
        return "MEDIUM"

    return "LOW"