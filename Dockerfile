# syntax=docker/dockerfile:1.7

# ═══════════════════════════════════════════════════════
# BUILDER STAGE — install dependencies into a venv
# ═══════════════════════════════════════════════════════
FROM python:3.11-slim AS builder

# Install uv (small statically-linked binary)
# Pin to a specific version for reproducibility
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

# uv config for reproducible installs
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv

WORKDIR /app

# Copy ONLY dependency manifests first (layer caching)
COPY backend/pyproject.toml backend/uv.lock ./backend/

# Install runtime deps only (no dev)
RUN --mount=type=cache,target=/root/.cache/uv \
    cd backend && uv sync --frozen --no-dev --no-install-project

# Now copy the actual source code
COPY backend/ ./backend/

# Install the project itself (in editable mode within container)
RUN --mount=type=cache,target=/root/.cache/uv \
    cd backend && uv sync --frozen --no-dev

# ═══════════════════════════════════════════════════════
# RUNTIME STAGE — minimal image with .venv from builder
# ═══════════════════════════════════════════════════════
FROM python:3.11-slim AS runtime

# Create non-root user
RUN groupadd --system --gid 1001 appgroup && \
    useradd --system --uid 1001 --gid appgroup \
            --home-dir /nonexistent --no-create-home \
            --shell /usr/sbin/nologin appuser

# Working dir owned by appuser
WORKDIR /app
RUN chown appuser:appgroup /app

# Copy venv from builder (preserve permissions)
COPY --from=builder --chown=appuser:appgroup /app/backend /app/backend

# Switch to non-root
USER appuser

# Make venv binaries available
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp

WORKDIR /app/backend

# Default command: run the API server (Step 3.4.b will refine via compose)
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
