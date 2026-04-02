from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt


SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
PASSWORD_HASH_ITERATIONS = int(os.getenv("PASSWORD_HASH_ITERATIONS", "390000"))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    encoded_salt = base64.b64encode(salt).decode("ascii")
    encoded_hash = base64.b64encode(derived_key).decode("ascii")
    return f"{PASSWORD_HASH_ITERATIONS}${encoded_salt}${encoded_hash}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        iterations_raw, encoded_salt, encoded_hash = hashed_password.split("$", 2)
        iterations = int(iterations_raw)
        salt = base64.b64decode(encoded_salt.encode("ascii"))
        expected_hash = base64.b64decode(encoded_hash.encode("ascii"))
    except (TypeError, ValueError):
        return False

    candidate_hash = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate_hash, expected_hash)


def create_token(data: dict) -> str:
    to_encode = data.copy()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expires_at
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
