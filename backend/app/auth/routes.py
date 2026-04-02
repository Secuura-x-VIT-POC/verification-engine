from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..core.limiter import limiter
from ..db.database import get_db
from .models import User
from .schemas import UserCredentials
from .utils import create_token, decode_token, hash_password, verify_password


router = APIRouter(tags=["auth"])
security = HTTPBearer()


@router.post("/register")
@limiter.limit("5/minute")
def register(request: Request, user: UserCredentials, db: Session = Depends(get_db)) -> dict[str, str]:
    existing = db.query(User).filter(User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    new_user = User(
        username=user.username,
        password_hash=hash_password(user.password),
    )
    db.add(new_user)
    db.commit()

    return {"message": "User registered successfully"}


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, user: UserCredentials, db: Session = Depends(get_db)) -> dict[str, str]:
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not verify_password(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token({"sub": user.username})
    return {
        "access_token": token,
        "token_type": "bearer",
    }


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    payload = decode_token(credentials.credentials)
    if payload is None or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    return str(payload["sub"])


@router.get("/protected")
def protected(user: str = Depends(get_current_user)) -> dict[str, str]:
    return {"message": f"Hello {user}, you are authorized!"}
