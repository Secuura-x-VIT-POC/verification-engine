from fastapi import FastAPI
from app.auth.routes import router as auth_router
from app.sessions.routes import router as session_router
from app.connectors.routes import router as connector_router
from app.db.database import Base, engine
from fastapi.middleware.cors import CORSMiddleware
from app.core.limiter import limiter
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

app = FastAPI()

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(session_router)
app.include_router(connector_router)

Base.metadata.create_all(bind=engine)

@app.get("/")
def root():
    return {"message": "Backend running"}