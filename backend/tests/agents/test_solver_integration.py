from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.solver.agent import SolverAgent
from app.agents.solver.schemas import SolverInput
from app.core.config import get_settings
from app.llm.client import DeepSeekClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not get_settings().DEEPSEEK_API_KEY,
        reason="DEEPSEEK_API_KEY not set (env or backend/.env); skipping live tests",
    ),
]

FIXTURE = Path(__file__).parent / "fixtures" / "sample_problems.json"


def _load_problems() -> list[SolverInput]:
    raw = json.loads(FIXTURE.read_text())
    return [SolverInput.model_validate(p) for p in raw]


@pytest.mark.parametrize("problem", _load_problems(), ids=lambda p: p.problem_id)
async def test_solver_against_real_deepseek(problem: SolverInput):
    # get_settings is cached; this picks up DEEPSEEK_API_KEY from env / .env.
    agent = SolverAgent(DeepSeekClient(get_settings()))

    output = await agent.solve(problem)

    assert output.problem_id == problem.problem_id
    assert "def " in output.code, f"code missing `def `: {output.code!r}"
    assert output.confidence >= 0.5, f"low confidence: {output.confidence}"
    assert output.plan_steps, "plan_steps empty"
    assert output.analysis.strip(), "analysis empty"
    assert output.explanation.strip(), "explanation empty"
