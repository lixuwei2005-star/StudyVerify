"""Unit tests for app.scripts.seed_failure_corpus (Step 6.3).

External boundaries (httpx.AsyncClient, AsyncSession, create_async_engine,
get_settings, input()) are all mocked. No real PG, no real API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scripts import seed_failure_corpus as seed

PROBLEM_FIXTURE = [
    {
        "problem_id": "py-001-sum-list",
        "problem_text": "Sum a list.",
        "entry_function": "sum_list",
        "test_cases": [
            {"input": "[1,2]", "expected": "3", "description": "basic"},
            {"input": "[]", "expected": "0", "description": "empty"},
            {"input": "[-1,1]", "expected": "0", "description": "mixed"},
        ],
        "reference_solution": "def sum_list(nums): return sum(nums)\n",
    },
    {
        "problem_id": "py-002-find-max",
        "problem_text": "Find max.",
        "entry_function": "find_max",
        "test_cases": [
            {"input": "[1,2]", "expected": "2", "description": "basic"},
            {"input": "[]", "expected": "None", "description": "empty"},
            {"input": "[-1,-2]", "expected": "-1", "description": "negs"},
        ],
        "reference_solution": "def find_max(n): return max(n) if n else None\n",
    },
]


VARIANTS = {
    "py-001-sum-list": [
        {"category": "off-by-one", "code": "def sum_list(nums):\n    return 0\n"},
        {"category": "wrong-base", "code": "def sum_list(nums):\n    return sum(nums) + 1\n"},
    ],
    "py-002-find-max": [
        {"category": "wrong-empty", "code": "def find_max(nums):\n    return nums[0]\n"},
    ],
}


def _write_fixtures(tmp_path: Path) -> Path:
    variants_path = tmp_path / "buggy_variants.json"
    variants_path.write_text(json.dumps(VARIANTS))
    return variants_path


def _settings_mock(database_url: str = "postgresql+asyncpg://u:p@localhost:5432/db") -> MagicMock:
    s = MagicMock()
    s.DATABASE_URL = database_url
    return s


def _row(**kwargs) -> MagicMock:
    """Mock SQLAlchemy row with attribute access and ._mapping."""
    m = MagicMock()
    for k, v in kwargs.items():
        setattr(m, k, v)
    return m


class _SessionStub:
    """AsyncSession test double with programmable execute() responses.

    The seed CLI calls `session.execute(EXISTS_SQL, ...)` once per variant
    (returns scalar None or 1), then once at the end with COUNT_SEEDED_SQL
    (returns rows). Track calls so tests can assert.
    """

    def __init__(
        self,
        *,
        existing_codes: set[str] | None = None,
        embedding_counts: dict[str, int] | None = None,
        deletion_plan: tuple[int, int, int] = (0, 0, 0),
    ):
        self.existing_codes = existing_codes or set()
        self.embedding_counts = embedding_counts or {}
        self.deletion_plan = deletion_plan
        self.executed: list[tuple[str, dict]] = []
        self.commits = 0

    async def execute(self, stmt, params=None):  # noqa: D401
        sql_text = str(stmt)
        self.executed.append((sql_text, params or {}))
        result = MagicMock()
        if (
            "FROM verifier_sessions v\n    JOIN solver_sessions s" in sql_text
            and "LIMIT 1" in sql_text
        ):
            code = (params or {}).get("student_code")
            present = code in self.existing_codes
            result.scalar_one_or_none = MagicMock(return_value=1 if present else None)
            return result
        if "GROUP BY s.problem_id" in sql_text and "embedding_status = 'success'" in sql_text:
            rows = [_row(problem_id=pid, n=n) for pid, n in self.embedding_counts.items()]
            result.all = MagicMock(return_value=rows)
            return result
        if "AS hints" in sql_text:
            h, v, s = self.deletion_plan
            result.one = MagicMock(return_value=_row(hints=h, verifiers=v, solvers=s))
            return result
        if "DELETE FROM" in sql_text:
            result.rowcount = 0
            return result
        result.scalar_one_or_none = MagicMock(return_value=None)
        result.all = MagicMock(return_value=[])
        return result

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _engine_mock() -> MagicMock:
    e = MagicMock()
    e.dispose = AsyncMock()
    return e


def _httpx_client_mock(
    *,
    solve_responses: list[dict] | None = None,
    verify_responses: list[dict] | None = None,
    raise_on_call: int | None = None,
) -> MagicMock:
    """Mock httpx.AsyncClient with .post returning canned JSON.

    raise_on_call: 0-indexed call number that should raise httpx.HTTPError.
    """
    solve_iter = iter(solve_responses or [])
    verify_iter = iter(verify_responses or [])
    call_idx = [0]

    async def _post(url, json=None, timeout=None):
        idx = call_idx[0]
        call_idx[0] += 1
        if raise_on_call is not None and idx == raise_on_call:
            import httpx

            raise httpx.HTTPError("simulated network failure")
        body = next(solve_iter) if "/solve" in url else next(verify_iter)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=body)
        return resp

    client = MagicMock()
    client.post = AsyncMock(side_effect=_post)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _patch_problem_lookup():
    return patch.object(
        seed,
        "_problem_lookup",
        return_value={p["problem_id"]: p for p in PROBLEM_FIXTURE},
    )


def _make_args(**overrides) -> argparse.Namespace:
    base = dict(
        variants="UNSET",
        api_base="http://localhost:8000",
        problem_filter=None,
        dry_run=False,
        delete_existing=False,
        yes_dev_db=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


# ---- Test 1: partial resume seeds only missing variants ----


@pytest.mark.asyncio
async def test_partial_resume_seeds_only_missing(tmp_path, capsys):
    variants_path = _write_fixtures(tmp_path)
    # Pre-seed: code for variant 0 of py-001 already exists in DB.
    existing = {VARIANTS["py-001-sum-list"][0]["code"]}
    session = _SessionStub(
        existing_codes=existing, embedding_counts={"py-001-sum-list": 1, "py-002-find-max": 1}
    )
    # 2 missing variants → 2 solve + 2 verify pairs
    client = _httpx_client_mock(
        solve_responses=[{"session_id": "s1"}, {"session_id": "s2"}],
        verify_responses=[
            {"session_id": "v1", "output": {"verified": False}},
            {"session_id": "v2", "output": {"verified": False}},
        ],
    )
    with (
        patch.object(seed, "create_async_engine", return_value=_engine_mock()),
        patch.object(seed, "AsyncSession", return_value=session),
        patch.object(seed, "get_settings", return_value=_settings_mock()),
        patch.object(seed.httpx, "AsyncClient", return_value=client),
        _patch_problem_lookup(),
    ):
        rc = await seed._run(_make_args(variants=str(variants_path)))
    assert rc == 0
    out = capsys.readouterr().out
    assert "attempted=3 seeded=2 skipped=1" in out


# ---- Test 2: exact duplicate variant is skipped ----


@pytest.mark.asyncio
async def test_exact_duplicate_skipped(tmp_path, capsys):
    variants_path = _write_fixtures(tmp_path)
    # All 3 variants already exist
    existing = {v["code"] for items in VARIANTS.values() for v in items}
    session = _SessionStub(existing_codes=existing)
    client = _httpx_client_mock()
    with (
        patch.object(seed, "create_async_engine", return_value=_engine_mock()),
        patch.object(seed, "AsyncSession", return_value=session),
        patch.object(seed, "get_settings", return_value=_settings_mock()),
        patch.object(seed.httpx, "AsyncClient", return_value=client),
        _patch_problem_lookup(),
    ):
        rc = await seed._run(_make_args(variants=str(variants_path)))
    assert rc == 0
    assert "attempted=3 seeded=0 skipped=3" in capsys.readouterr().out
    assert client.post.await_count == 0


# ---- Test 3: --problem-filter limits to one problem ----


@pytest.mark.asyncio
async def test_problem_filter_limits_to_one_problem(tmp_path, capsys):
    variants_path = _write_fixtures(tmp_path)
    session = _SessionStub()
    client = _httpx_client_mock(
        solve_responses=[{"session_id": "s1"}, {"session_id": "s2"}],
        verify_responses=[
            {"session_id": "v1", "output": {"verified": False}},
            {"session_id": "v2", "output": {"verified": False}},
        ],
    )
    with (
        patch.object(seed, "create_async_engine", return_value=_engine_mock()),
        patch.object(seed, "AsyncSession", return_value=session),
        patch.object(seed, "get_settings", return_value=_settings_mock()),
        patch.object(seed.httpx, "AsyncClient", return_value=client),
        _patch_problem_lookup(),
    ):
        rc = await seed._run(
            _make_args(variants=str(variants_path), problem_filter="py-001-sum-list")
        )
    assert rc == 0
    out = capsys.readouterr().out
    assert "attempted=2 seeded=2" in out
    assert "py-002-find-max" not in out  # filter excluded


# ---- Test 4: per-row API failure logs and continues ----


@pytest.mark.asyncio
async def test_per_row_api_failure_logs_and_continues(tmp_path, capsys):
    variants_path = _write_fixtures(tmp_path)
    session = _SessionStub()
    # Call sequence: solve, verify, solve(FAIL), [skipped], solve, verify
    # raise_on_call=2 → second solve (third post overall) fails
    client = _httpx_client_mock(
        solve_responses=[
            {"session_id": "s1"},
            {"session_id": "s3"},
        ],
        verify_responses=[
            {"session_id": "v1", "output": {"verified": False}},
            {"session_id": "v3", "output": {"verified": False}},
        ],
        raise_on_call=2,  # third post (= second solve) fails
    )
    with (
        patch.object(seed, "create_async_engine", return_value=_engine_mock()),
        patch.object(seed, "AsyncSession", return_value=session),
        patch.object(seed, "get_settings", return_value=_settings_mock()),
        patch.object(seed.httpx, "AsyncClient", return_value=client),
        _patch_problem_lookup(),
    ):
        rc = await seed._run(_make_args(variants=str(variants_path)))
    assert rc == 0
    out = capsys.readouterr().out
    assert "attempted=3" in out
    assert "failed=1" in out
    assert "FAIL pid=" in out


# ---- Test 5: accidental-pass variant logs warning ----


@pytest.mark.asyncio
async def test_accidental_pass_logged_with_warning(tmp_path, capsys):
    variants_path = _write_fixtures(tmp_path)
    session = _SessionStub()
    client = _httpx_client_mock(
        solve_responses=[{"session_id": f"s{i}"} for i in range(1, 4)],
        verify_responses=[
            {"session_id": "v1", "output": {"verified": True}},  # accidental
            {"session_id": "v2", "output": {"verified": False}},
            {"session_id": "v3", "output": {"verified": False}},
        ],
    )
    with (
        patch.object(seed, "create_async_engine", return_value=_engine_mock()),
        patch.object(seed, "AsyncSession", return_value=session),
        patch.object(seed, "get_settings", return_value=_settings_mock()),
        patch.object(seed.httpx, "AsyncClient", return_value=client),
        _patch_problem_lookup(),
    ):
        rc = await seed._run(_make_args(variants=str(variants_path)))
    assert rc == 0
    out = capsys.readouterr().out
    assert "accidental_pass=1" in out
    assert "verified=true (accidental_pass)" in out


# ---- Test 6: --dry-run returns counts, no API calls ----


@pytest.mark.asyncio
async def test_dry_run_returns_counts_no_api_calls(tmp_path, capsys):
    variants_path = _write_fixtures(tmp_path)
    client = _httpx_client_mock()
    fake_engine = _engine_mock()
    with (
        patch.object(seed, "create_async_engine", return_value=fake_engine),
        patch.object(seed, "get_settings", return_value=_settings_mock()),
        patch.object(seed.httpx, "AsyncClient", return_value=client),
        _patch_problem_lookup(),
    ):
        rc = await seed._run(_make_args(variants=str(variants_path), dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "WOULD-SEED" in out
    assert "no API calls, no DB writes" in out
    assert client.post.await_count == 0
    fake_engine.dispose.assert_not_called()  # short-circuit before engine creation


# ---- Test 7: --delete-existing without --yes-dev-db prompts for confirmation ----


@pytest.mark.asyncio
async def test_delete_existing_without_yes_dev_db_requires_confirmation(tmp_path, capsys):
    variants_path = _write_fixtures(tmp_path)
    session = _SessionStub(deletion_plan=(0, 5, 2))
    with (
        patch.object(seed, "create_async_engine", return_value=_engine_mock()),
        patch.object(seed, "AsyncSession", return_value=session),
        patch.object(seed, "get_settings", return_value=_settings_mock()),
        patch("builtins.input", return_value="no"),
        _patch_problem_lookup(),
    ):
        rc = await seed._run(_make_args(variants=str(variants_path), delete_existing=True))
    assert rc == 1
    out = capsys.readouterr()
    assert "Will delete:" in out.out
    assert session.commits == 0  # nothing committed


# ---- Test 8: non-localhost DATABASE_URL exits 1 before destructive deletion ----


@pytest.mark.asyncio
async def test_force_reseed_non_localhost_database_url_exits(tmp_path, capsys):
    variants_path = _write_fixtures(tmp_path)
    bad_url = "postgresql+asyncpg://u:p@prod-db.example.com:5432/x"
    with (
        patch.object(seed, "create_async_engine", return_value=_engine_mock()),
        patch.object(seed, "get_settings", return_value=_settings_mock(database_url=bad_url)),
        _patch_problem_lookup(),
    ):
        with pytest.raises(SystemExit) as exc:
            await seed._run(
                _make_args(variants=str(variants_path), delete_existing=True, yes_dev_db=True)
            )
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "REFUSED" in err
    assert "prod-db.example.com" in err


# ---- Test 9: --delete-existing --yes-dev-db deletes in FK order ----


@pytest.mark.asyncio
async def test_delete_in_fk_order(tmp_path, capsys):
    variants_path = _write_fixtures(tmp_path)
    session = _SessionStub(deletion_plan=(2, 5, 2))
    client = _httpx_client_mock(
        solve_responses=[{"session_id": f"s{i}"} for i in range(1, 4)],
        verify_responses=[
            {"session_id": f"v{i}", "output": {"verified": False}} for i in range(1, 4)
        ],
    )
    with (
        patch.object(seed, "create_async_engine", return_value=_engine_mock()),
        patch.object(seed, "AsyncSession", return_value=session),
        patch.object(seed, "get_settings", return_value=_settings_mock()),
        patch.object(seed.httpx, "AsyncClient", return_value=client),
        _patch_problem_lookup(),
    ):
        rc = await seed._run(
            _make_args(variants=str(variants_path), delete_existing=True, yes_dev_db=True)
        )
    assert rc == 0
    deletes = [sql for sql, _ in session.executed if "DELETE FROM" in sql]
    assert len(deletes) == 3
    # Verify ordering: hint_sessions FIRST, then verifier_sessions, then solver_sessions
    assert "hint_sessions" in deletes[0]
    assert "verifier_sessions" in deletes[1]
    assert "solver_sessions" in deletes[2]


# ---- Test 10: deletion plan is printed BEFORE any DELETE executes ----


@pytest.mark.asyncio
async def test_deletion_plan_printed_before_executing(tmp_path, capsys):
    variants_path = _write_fixtures(tmp_path)
    session = _SessionStub(deletion_plan=(3, 7, 4))
    client = _httpx_client_mock(
        solve_responses=[{"session_id": f"s{i}"} for i in range(1, 4)],
        verify_responses=[
            {"session_id": f"v{i}", "output": {"verified": False}} for i in range(1, 4)
        ],
    )
    with (
        patch.object(seed, "create_async_engine", return_value=_engine_mock()),
        patch.object(seed, "AsyncSession", return_value=session),
        patch.object(seed, "get_settings", return_value=_settings_mock()),
        patch.object(seed.httpx, "AsyncClient", return_value=client),
        _patch_problem_lookup(),
    ):
        await seed._run(
            _make_args(variants=str(variants_path), delete_existing=True, yes_dev_db=True)
        )
    out = capsys.readouterr().out
    plan_idx = out.index("Will delete:")
    deleted_idx = out.index("Deleted existing rows")
    # The "Deleted existing rows" log line is printed AFTER deletion runs.
    assert plan_idx < deleted_idx
    assert "3 hint_sessions, 7 verifier_sessions, 4 solver_sessions" in out
