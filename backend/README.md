# StudyVerify Backend

FastAPI service for StudyVerify.

## Setup

Requires Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run uvicorn app.main:app --reload
```

## Common Commands

```bash
uv run pytest -v          # tests
uv run ruff check .       # lint
uv run ruff format .      # format
uv run mypy app           # type check
```

## Configuration

Copy `.env.example` to `.env` and edit as needed. All settings have sane defaults.
