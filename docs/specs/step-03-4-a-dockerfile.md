# StudyVerify — Step 3.4.a: Multi-stage Dockerfile Spec

## Goal
Build a production-ready FastAPI Docker image with multi-stage 
build, non-root runtime user, and uv-managed dependencies. Verify 
image size, build cache behavior, and bare container startup. 

This step is **isolated**: no docker-compose changes, no env wiring, 
no PG connection. The only thing being validated is "can this image 
build, start, and respond to a basic command".

## Why So Narrow
Docker debugging is exponentially harder when multiple things change 
at once: a build issue + a network issue + an env-var issue = three 
problems disguised as one. Locking down the Dockerfile in isolation 
ensures any later compose/env bug is unambiguously elsewhere.

## Scope
- `Dockerfile` (project root) using multi-stage build
- `.dockerignore` (project root) — excludes .venv, __pycache__, .env*, 
  .pytest_cache, tests/, docs/, .git/, etc.
- Build target: arm64 (Apple Silicon native, no Rosetta)
- Base: `python:3.11-slim`
- Final image size target: < 300 MB
  (BuildKit's default SBOM + provenance attestations inflate the
  reported size by ~95 MB without changing actual layer content;
  we disable both via `--provenance=false --sbom=false` in the
  Makefile build targets)
- Non-root user `appuser` for runtime
- Startup smoke: `docker run --rm <image> python -c "import app.main"` 
  succeeds (just imports the module, no server)

## Out of Scope (this step)
- ❌ Connecting to Postgres → 3.4.b
- ❌ Reading DATABASE_URL from env → 3.4.b
- ❌ Running alembic upgrade on startup → 3.4.b
- ❌ docker-compose service definition → 3.4.b
- ❌ healthcheck → 3.4.b

## Files to Create

- `Dockerfile` (project root)
- `.dockerignore` (project root)
- `Makefile` — add `docker-build` and `docker-run-smoke` targets

## Dockerfile Structure

```dockerfile
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

# uv is intentionally NOT installed in the runtime stage. The
# venv copied from the builder already contains every executable
# the app needs (uvicorn, alembic). 3.4.b will invoke alembic
# directly via `/app/backend/.venv/bin/alembic`, not `uv run`.
# Keeping the runtime image free of uv saves ~48 MB and removes
# a debugging tool from the production attack surface.

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
```

### Design notes
- **`# syntax=docker/dockerfile:1.7`** — enables modern features 
  like `--from` heredocs and better caching
- **`COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv`** —  
  this is uv's official distroless image; we just lift the binary. 
  Pin to a specific version for reproducibility (latest moves)
- **`UV_LINK_MODE=copy`** — required when `.venv` will be moved 
  across stages (default `hardlink` mode breaks cross-stage copy)
- **`UV_COMPILE_BYTECODE=1`** — pre-compiles .pyc, ~10% faster 
  startup
- **Layer split**: `pyproject.toml + uv.lock` first, then 
  `--no-install-project`, THEN copy source, THEN final sync. 
  Editing a Python file rebuilds only the last layer (~3s), not 
  the dep install layer (~30s)
- **Non-root user (uid 1001)** — defense in depth; if app is RCE'd, 
  no root inside container
- **Direct `uvicorn` CMD** — the venv is already on PATH, so runtime 
  startup avoids extra uv process overhead and hidden lock checks
- **`ENV PATH=...venv/bin:$PATH`** — lets `uvicorn` and `alembic` 
  resolve directly without `uv run` if needed (fallback ergonomics)

## .dockerignore

```
# VCS
.git/
.gitignore
.gitattributes

# Virtual environments (we install fresh in builder)
**/.venv/
**/venv/
**/env/

# Python caches
**/__pycache__/
**/*.pyc
**/*.pyo
**/.pytest_cache/
**/.ruff_cache/
**/.mypy_cache/

# Environment files (NEVER bake secrets into images)
# Comments must be on their own line in .dockerignore
.env*
**/.env*
!.env.example
!**/.env.example
!.env.docker.example

# Tests and dev files (out of runtime image)
backend/tests/
backend/htmlcov/
backend/.coverage
backend/coverage.xml

# Docs and specs (out of runtime image)
docs/
*.md
# Allow these markdown files
!README.md
!backend/README.md

# IDE / OS
.vscode/
.idea/
.DS_Store
*.swp

# CI / scripts (not needed in runtime)
scripts/
.github/

# Build artifacts
**/dist/
**/build/
**/*.egg-info/

# Docker itself (would cause recursion)
Dockerfile
.dockerignore
docker-compose.yml
docker-compose.override.yml
Makefile
```

⚠️ **`.dockerignore` semantics differ from `.gitignore`**:
- `.dockerignore` is processed by the Docker daemon **before** 
  build context is sent
- The `**` pattern is supported (similar to git but slightly 
  different edge cases)
- Excluding `.git/` is important — without it, every commit changes 
  build context and busts cache
- Excluding `.env*` is **critical for security** — secrets must 
  NEVER end up in image layers, even if the layer is later removed 
  (it persists in image history)

## Makefile Additions

Add these targets to the existing Makefile:

```makefile
# ═══ Docker image management (Step 3.4.a) ═══

DOCKER_IMAGE := studyverify-api
DOCKER_TAG := dev

.PHONY: docker-build docker-build-fresh docker-run-smoke docker-image-size

docker-build:
	@echo "Building $(DOCKER_IMAGE):$(DOCKER_TAG) for native arm64..."
	docker build \
		--platform=linux/arm64 \
		-t $(DOCKER_IMAGE):$(DOCKER_TAG) \
		.

docker-build-fresh:
	@echo "Building from scratch (no cache)..."
	docker build \
		--platform=linux/arm64 \
		--no-cache \
		-t $(DOCKER_IMAGE):$(DOCKER_TAG) \
		.

docker-run-smoke:
	@echo "Smoke test: import app.main inside the image..."
	docker run --rm $(DOCKER_IMAGE):$(DOCKER_TAG) \
		python -c "import app.main; print('✅ Module imports successfully')"

docker-image-size:
	@docker images $(DOCKER_IMAGE):$(DOCKER_TAG) \
		--format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
```

Update `make help` target's text to include these.

## Verification Checklist

1. **Files exist**:
   - `Dockerfile` at project root
   - `.dockerignore` at project root
   - Makefile has new targets

2. **`.dockerignore` actually excludes secrets**:
   - Run `tar -czh --exclude-from=.dockerignore -f /dev/null . 2>&1 | head -20` 
     to verify (rough simulation)
   - Or: build with `--progress=plain` and watch the "transferring 
     context" line — should be a few MB, not hundreds of MB
   - Verify `.env*` files are NOT in final context

3. **First `make docker-build`**:
   - Completes successfully
   - Total build time logged (expect 30-90s first time, mostly uv sync)
   - No warnings about deprecated syntax

4. **Image size**:
   - `make docker-image-size` shows < 250 MB
   - Compare to baseline `python:3.11-slim` (~125 MB) — our overhead 
     should be the .venv + app code

5. **Layer caching**:
   - Touch a backend Python file (e.g., `touch backend/app/main.py`)
   - Re-run `make docker-build`
   - Should reuse all layers EXCEPT the final source-copy + sync
   - Total time < 10s
   - The dep-install layer must NOT re-run

6. **Smoke test**:
   - `make docker-run-smoke` succeeds with "Module imports successfully"
   - This proves: image structure correct, .venv accessible, 
     app code copied, Python path resolved

7. **Non-root verification**:
   - `docker run --rm studyverify-api:dev id` shows uid=1001 
     (not 0 / root)

8. **Multi-arch sanity**:
   - `docker inspect studyverify-api:dev --format '{{.Architecture}}'` 
     reports `arm64`
   - No "platform mismatch" warnings during build

## What NOT to do
- DO NOT bake secrets into the image (`COPY .env*` is forbidden)
- DO NOT use `python:3.11` (without `-slim`) — it's ~900MB base, 
  adds nothing useful for our needs
- DO NOT use `python:alpine` — uv has issues with musl libc, 
  asyncpg compilation also troublesome on alpine
- DO NOT skip `--no-dev` in builder uv sync — pulls in pytest etc., 
  bloating image
- DO NOT use a uv version older than the one that generated 
  uv.lock. Verify with `uv --version` locally and pin the same 
  major.minor in the Dockerfile.
- DO NOT chain `uv run` + `uvicorn` in CMD when PATH already 
  exposes the venv. Direct invocation (`uvicorn app.main:app ...`) 
  is faster and avoids hidden lock checks.
- DO NOT put inline `# comments` on the same line as a pattern 
  in .dockerignore. The parser does NOT strip them; they become 
  part of the pattern.
- DO NOT skip the cache mount on uv sync — without it, every 
  layer rebuild re-downloads wheels.
- DO NOT hardcode `--platform=linux/amd64` — Apple Silicon would 
  emulate via Rosetta 2, slow
- DO NOT use a single-stage build — image bloats to ~600MB
- DO NOT install uv in builder via `pip install uv` — slower and 
  pulls in pip's dependency tree; use the official uv image
- DO NOT run as root — basic security hygiene
- DO NOT use `latest` tag for uv version — pin
- DO NOT copy `.git/` into the image — destroys cache, leaks history
- DO NOT bake debugging tools (uv, curl, vim, strace, etc.) into the
  runtime image. The runtime stage should contain only what the app
  needs to run. For ad-hoc debugging, use `docker exec -it <container>
  sh` plus `apt-get install` on an ephemeral basis, or run a sidecar
  image that has the tools you need.

## Estimated Time
- Writing Dockerfile + .dockerignore: 30 min
- Makefile additions: 5 min
- First build (cold cache): ~90 sec
- Verification: 15-20 min
- **Total: ~1 hour active work**
