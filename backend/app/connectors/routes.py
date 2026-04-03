from fastapi import APIRouter, Depends
from app.connectors.broker import call_connector
router = APIRouter()

from app.auth.routes import get_current_user

@router.post("/connector/test")
def test_connector(
    data: dict,
    user: str = Depends(get_current_user)
):
    return call_connector(data)