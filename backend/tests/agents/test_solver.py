from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.agents.solver.agent import SolverAgent, SolverError
from app.agents.solver.schemas import PlanStep, SolverInput, TestCase
from app.llm.client import DeepSeekClient
from app.llm.exceptions import LLMError, LLMTimeoutError


def _input() -> SolverInput:
    return SolverInput(
        problem_id="py-001-sum-list",
        problem_text="Write sum_list(nums) returning the sum, or 0 if empty.",
        test_cases=[
            TestCase(input="[1,2,3]", expected="6", description="basic"),
            TestCase(input="[]", expected="0", description="empty"),
        ],
    )


def _good_responses() -> list[str]:
    analysis = (
        "We need a function sum_list that takes a list of integers and returns "
        "their sum. The empty-list case must return 0."
    )
    plan = json.dumps(
        {
            "steps": [
                {"step_number": 1, "action": "Define sum_list(nums)", "rationale": "signature"},
                {"step_number": 2, "action": "Initialize total = 0", "rationale": "accumulator"},
                {"step_number": 3, "action": "Iterate and add", "rationale": "core logic"},
                {"step_number": 4, "action": "Return total", "rationale": "result"},
            ]
        }
    )
    code_src = (
        "def sum_list(nums):\n"
        "    total = 0\n"
        "    for n in nums:\n"
        "        total += n\n"
        "    return total\n"
    )
    code = json.dumps({"code": code_src, "explanation": "Linear scan into total."})
    return [analysis, plan, code]


def _agent_with_responses(responses: list[str | Exception]) -> tuple[SolverAgent, AsyncMock]:
    client = AsyncMock(spec=DeepSeekClient)
    client.chat = AsyncMock(side_effect=responses)
    return SolverAgent(client), client.chat


async def test_solve_happy_path_calls_chat_three_times_in_order():
    agent, chat = _agent_with_responses(_good_responses())

    out = await agent.solve(_input())

    assert chat.await_count == 3
    assert out.problem_id == "py-001-sum-list"
    assert out.analysis.startswith("We need a function sum_list")
    assert [s.step_number for s in out.plan_steps] == [1, 2, 3, 4]
    assert "def sum_list" in out.code
    assert out.confidence == pytest.approx(1.0)

    # Stage 1: analyze — no json_mode.
    a_kwargs = chat.await_args_list[0].kwargs
    assert a_kwargs.get("json_mode", False) is False
    # Stages 2 & 3: json_mode required.
    assert chat.await_args_list[1].kwargs["json_mode"] is True
    assert chat.await_args_list[2].kwargs["json_mode"] is True


async def test_solve_propagates_llm_error_as_solver_error_with_step_context():
    agent, _ = _agent_with_responses([LLMError("upstream 500")])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "analyze"
    assert ei.value.problem_id == "py-001-sum-list"


async def test_solve_propagates_timeout_in_plan_step():
    analysis, _plan, _code = _good_responses()
    agent, _ = _agent_with_responses([analysis, LLMTimeoutError("slow")])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "plan"


async def test_solve_raises_on_malformed_plan_json():
    analysis, _, code = _good_responses()
    agent, _ = _agent_with_responses([analysis, "not-json-at-all", code])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "plan"
    assert "invalid JSON" in str(ei.value)


async def test_solve_raises_when_plan_missing_steps_key():
    analysis, _, code = _good_responses()
    agent, _ = _agent_with_responses([analysis, json.dumps({"items": []}), code])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "plan"


async def test_solve_raises_on_malformed_code_json():
    analysis, plan, _ = _good_responses()
    agent, _ = _agent_with_responses([analysis, plan, json.dumps({"code": "x"})])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "code"


@pytest.mark.parametrize(
    "analysis,plan_steps,code,expected",
    [
        (
            "x" * 100,
            [PlanStep(step_number=i, action="a", rationale="r") for i in (1, 2, 3)],
            "def f(): pass",
            1.0,
        ),
        (
            "short",
            [PlanStep(step_number=i, action="a", rationale="r") for i in (1, 2)],
            "def f(): pass",
            0.8,
        ),
        ("x" * 100, [PlanStep(step_number=1, action="a", rationale="r")], "def f(): pass", 0.8),
        (
            "x" * 100,
            [PlanStep(step_number=i, action="a", rationale="r") for i in (1, 2)],
            "no_function_here",
            0.7,
        ),
        ("short", [], "no_function_here", 0.3),
    ],
)
def test_compute_confidence_table(analysis, plan_steps, code, expected):
    got = SolverAgent._compute_confidence(analysis, plan_steps, code)
    assert got == pytest.approx(expected)
