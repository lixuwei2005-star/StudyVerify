from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.solver import SolverError, SolverInput
from app.db.session import get_db_session
from app.dependencies import get_solver_service
from app.llm.exceptions import LLMError, LLMTimeoutError
from app.schemas.solver_session import SolveResponse
from app.services.solver_service import SolverService

logger = logging.getLogger("app.api.solver")

# main.py owns the /api/v1 prefix — do not duplicate it here.
router = APIRouter(tags=["solver"])


@router.post("/solve", response_model=SolveResponse)
async def solve(
    solver_input: SolverInput,
    service: SolverService = Depends(get_solver_service),
    session: AsyncSession = Depends(get_db_session),
) -> SolveResponse:
    try:
        row, output = await service.solve_and_persist(session, solver_input)
    except LLMTimeoutError as exc:
        logger.warning("solve.timeout problem_id=%s err=%s", solver_input.problem_id, exc)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM provider timed out",
        ) from exc
    except (LLMError, SolverError) as exc:
        logger.error("solve.failed problem_id=%s err=%s", solver_input.problem_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return SolveResponse(session_id=row.id, output=output)
