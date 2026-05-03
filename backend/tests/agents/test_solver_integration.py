from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.solver.agent import SolverAgent
from app.agents.solver.schemas import SolverInput
from app.core.config import get_settings
from app.llm.client import DeepSeekClient
from app.sandbox.runner import PythonSubprocessRunner

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not get_settings().DEEPSEEK_API_KEY,
        reason="DEEPSEEK_API_KEY not set (env or backend/.env); skipping live tests",
    ),
]

FIXTURE = Path(__file__).parent / "fixtures" / "sample_problems.json"


def _load_problems(limit: int | None = None) -> list[SolverInput]:
    raw = json.loads(FIXTURE.read_text())
    if limit is not None:
        raw = raw[:limit]
    return [SolverInput.model_validate(p) for p in raw]


async def _run_solver_assertions(problem: SolverInput) -> None:
    # get_settings is cached; this picks up DEEPSEEK_API_KEY from env / .env.
    settings = get_settings()
    agent = SolverAgent(
        client=DeepSeekClient(settings),
        runner=PythonSubprocessRunner(),
        sandbox_timeout_seconds=settings.SANDBOX_TIMEOUT_SECONDS,
        sandbox_memory_mb=settings.SANDBOX_MEMORY_MB,
    )

    output = await agent.solve(problem)

    assert output.problem_id == problem.problem_id
    assert "def " in output.code, f"code missing `def `: {output.code!r}"
    assert output.confidence >= 0.5, f"low confidence: {output.confidence}"
    assert output.plan_steps, "plan_steps empty"
    assert output.analysis.strip(), "analysis empty"
    assert output.explanation.strip(), "explanation empty"
    assert output.verified is True, f"sandbox verification failed: {output.test_results}"
    assert len(output.test_results) == len(problem.test_cases)
    assert all(r.passed for r in output.test_results)
    # Sample problems are tractable; first-try success is expected. If a real
    # run trips this, investigate prompts/model rather than relaxing the assert.
    assert output.retry_used is False


# Default integration sweep: first 3 problems only. Cost budget for the
# routine `pytest -m integration` run was a 10x amplifier when this
# parametrized over all 10 fixtures; capping to 3 keeps the suite cheap. The
# full 10-problem coverage lives in the @pytest.mark.slow variant below.
@pytest.mark.parametrize("problem", _load_problems(limit=3), ids=lambda p: p.problem_id)
async def test_solver_against_real_deepseek(problem: SolverInput) -> None:
    await _run_solver_assertions(problem)


# Full 10-problem coverage; opt-in via `pytest -m slow`. Real-DeepSeek calls
# for every fixture, ~5-10 min, ~\$0.05 in token cost.
@pytest.mark.slow
@pytest.mark.parametrize("problem", _load_problems(), ids=lambda p: p.problem_id)
async def test_solver_against_real_deepseek_full(problem: SolverInput) -> None:
    await _run_solver_assertions(problem)
