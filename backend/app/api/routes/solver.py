from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.agents.solver import SolverAgent, SolverError, SolverInput, SolverOutput
from app.agents.solver.agent import get_solver_agent
from app.llm.exceptions import LLMError, LLMTimeoutError

logger = logging.getLogger("app.api.solver")

router = APIRouter(tags=["solver"])


@router.post("/solve", response_model=SolverOutput)
async def solve(
    request: SolverInput,
    agent: SolverAgent = Depends(get_solver_agent),
) -> SolverOutput:
    try:
        return await agent.solve(request)
    except LLMTimeoutError as exc:
        logger.warning("solve.timeout problem_id=%s err=%s", request.problem_id, exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM provider timed out",
        ) from exc
    except (LLMError, SolverError) as exc:
        logger.error("solve.failed problem_id=%s err=%s", request.problem_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
