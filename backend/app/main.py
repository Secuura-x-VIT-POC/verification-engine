from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .api.routes import router as api_router
from .auth.routes import router as auth_router
from .connectors.routes import router as connector_router
from .core.limiter import SLOWAPI_AVAILABLE, limiter
from .db.database import engine, init_db
from .sessions.routes import router as session_router

try:
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
except ImportError:  # pragma: no cover - optional until dependencies are installed
    _rate_limit_exceeded_handler = None
    RateLimitExceeded = None
    SlowAPIMiddleware = None


app = FastAPI()

# CORS middleware must be added first (last in add_middleware chain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

if SLOWAPI_AVAILABLE and SlowAPIMiddleware is not None:
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if api_router is not None:
    app.include_router(api_router)
app.include_router(auth_router)
app.include_router(session_router)
app.include_router(connector_router)


@app.on_event("startup")
def startup_event() -> None:
    init_db()


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Backend is running"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready"}
