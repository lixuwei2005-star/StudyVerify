# StudyVerify — Project Conventions

**Project:** StudyVerify — Verification-driven AI learning companion.

## Tooling

- **Python:** 3.11 only (use `python3.11` explicitly), managed by **uv**.
- **Package manager:** `uv add` / `uv sync`. Never use `pip` directly. Never use `requirements.txt`.
- **Style:** `ruff format` + `ruff check`, line length 100.
- **Imports:** absolute imports from `app.*`.

## Commit Style

Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

## Testing

Every new feature requires a test. Run `uv run pytest -v` before committing.

## Do Not Commit

`.env`, `__pycache__/`, `.venv/`, IDE files (`.vscode/`, `.idea/`), `.DS_Store`.
