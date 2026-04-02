import hmac
import hashlib
import os
import secrets

SECRET_KEY = os.getenv("HMAC_SECRET", "dev_secret").encode()


def generate_nonce() -> bytes:
    # 256-bit nonce
    return secrets.token_bytes(32)


def compute_document_digest(document_bytes: bytes) -> bytes:
    return hashlib.sha256(document_bytes).digest()


def generate_commitment(document_bytes: bytes, nonce: bytes, scope_tag: str) -> str:
    digest = compute_document_digest(document_bytes)

    message = scope_tag.encode() + digest + nonce

    return hmac.new(
        SECRET_KEY,
        message,
        hashlib.sha256
    ).hexdigest()