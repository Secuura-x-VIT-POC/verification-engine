from __future__ import annotations

from ..db.connection import get_db_connection
from ..workflow.service import start_verification

try:
    from fastapi import APIRouter, Depends
except ImportError:  # pragma: no cover - optional until FastAPI is installed
    APIRouter = None
    Depends = None


def verify_session(session_id: str, conn) -> dict[str, str]:
    return {"status": start_verification(conn, session_id)}


if APIRouter is not None and Depends is not None:
    router = APIRouter()

    @router.post("/session/{session_id}/verify")
    def verify_session_route(session_id: str, conn=Depends(get_db_connection)):
        return verify_session(session_id, conn)
else:  # pragma: no cover - makes the module import-safe without FastAPI
    router = None
