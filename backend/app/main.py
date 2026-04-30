from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, health_db, sessions, solver, verify
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import dispose_engine

setup_logging()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await dispose_engine()


app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)
app.include_router(health.router)
app.include_router(health_db.router)
app.include_router(solver.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(verify.router, prefix="/api/v1")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "StudyVerify API. See /docs for OpenAPI spec."}
