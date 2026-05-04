from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "studyverify-backend"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"
    ENV: str = "development"

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_REASONING_EFFORT: str = "none"
    LLM_TIMEOUT_SECONDS: int = 30
    LLM_MAX_RETRIES: int = 3  # DEPRECATED in 6.1 — gateway owns
    # retry now (3 attempts hardcoded in gateway.MAX_ATTEMPTS_PER_PROVIDER).
    # Field kept for .env compatibility; Step 9 will reconcile retry policy.

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    LLM_FALLBACK_ENABLED: bool = False
    LLM_FALLBACK_PROVIDER: str = "openai"

    EMBEDDING_MODEL: str = "text-embedding-3-small"
    RAG_ENABLED: bool = True
    RAG_TOP_K: int = 3
    # Raised from 0.7 in Step 6.2 Phase 7 hardening: lower thresholds let the
    # LLM see weakly-similar past diagnoses and biased hints toward algorithm
    # specifics. Real fix is the prompt rule + forbidden-phrase filter; this
    # is belt-and-suspenders to reduce noise.
    RAG_MIN_SIMILARITY: float = 0.75

    SANDBOX_TIMEOUT_SECONDS: int = 5
    SANDBOX_MEMORY_MB: int = 128
    SANDBOX_PYTHON_PATH: str = ""  # empty = resolve to sys.executable at runtime

    # Required: set in backend/.env, e.g.
    #   postgresql+asyncpg://studyverify:<password>@localhost:5432/studyverify
    # Empty triggers loud-fail at engine creation rather than a misleading auth error later.
    DATABASE_URL: str = ""
    DATABASE_URL_TEST: str = "sqlite+aiosqlite:///:memory:"
    DB_ECHO_SQL: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT_SECONDS: int = 30

    # CORS — frontend browser origins allowed to call the API. Exact origins
    # are a CSV list; allow_origin_regex covers Vercel preview deploys (one
    # unique subdomain per PR). Starlette's CORSMiddleware does not treat
    # `https://*.vercel.app` as a wildcard inside allow_origins — preview
    # URLs must go through allow_origin_regex.
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,https://studyverify.vercel.app"
    CORS_ALLOW_ORIGIN_REGEX: str = r"https://[a-zA-Z0-9-]+\.vercel\.app"


@lru_cache
def get_settings() -> Settings:
    return Settings()
