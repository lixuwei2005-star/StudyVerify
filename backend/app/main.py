from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, health_db, hint, sessions, solver, verify
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import dispose_engine

setup_logging()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await dispose_engine()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_split_csv(settings.CORS_ALLOWED_ORIGINS),
    allow_origin_regex=settings.CORS_ALLOW_ORIGIN_REGEX or None,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(health.router)
app.include_router(health_db.router)
app.include_router(solver.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(verify.router, prefix="/api/v1")
app.include_router(hint.router, prefix="/api/v1")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "StudyVerify API. See /docs for OpenAPI spec."}
