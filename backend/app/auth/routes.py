from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.auth.schemas import UserCreate
from .utils import create_token, decode_token
from app.auth.models import User
from app.auth.utils import hash_password, verify_password
from app.db.database import get_db
from sqlalchemy.orm import Session
from app.core.limiter import limiter
router = APIRouter()
security = HTTPBearer()

@router.post("/register")
@limiter.limit("5/minute")
def register(request: Request,user: UserCreate, db: Session = Depends(get_db)):

    existing = db.query(User).filter(User.username == user.username).first()

    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    new_user = User(
        username=user.username,
        password=hash_password(user.password)
    )

    db.add(new_user)
    db.commit()

    return {"message": "User registered successfully"}

@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request,user: UserCreate, db: Session = Depends(get_db)):

    db_user = db.query(User).filter(User.username == user.username).first()

    if not db_user or not verify_password(user.password, db_user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token({"sub": user.username})

    return {
        "access_token": token,
        "token_type": "bearer"
    }

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = decode_token(token)

    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    return payload["sub"]

@router.get("/protected")
def protected(user: str = Depends(get_current_user)):
    return {"message": f"Hello {user}, you are authorized!"}