from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth.routes import get_current_user
from .broker import call_connector


router = APIRouter(tags=["connectors"])


@router.post("/connector/test")
def test_connector(
    data: dict,
    connector: str = "vit_registry",
    user: str = Depends(get_current_user),
) -> dict:
    try:
        return call_connector(data, connector)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
