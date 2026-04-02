from __future__ import annotations

from pydantic import BaseModel


class UserCredentials(BaseModel):
    username: str
    password: str
