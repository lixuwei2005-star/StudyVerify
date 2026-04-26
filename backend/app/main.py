from fastapi import FastAPI

from app.api.routes import health
from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging()
settings = get_settings()

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)
app.include_router(health.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "StudyVerify API. See /docs for OpenAPI spec."}
