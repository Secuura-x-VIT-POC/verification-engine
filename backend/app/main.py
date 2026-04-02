from __future__ import annotations

from fastapi import FastAPI

from .api.routes import router as api_router


app = FastAPI()

if api_router is not None:
    app.include_router(api_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Backend is running"}
