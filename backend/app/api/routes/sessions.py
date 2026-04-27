from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.dependencies import get_solver_repository
from app.repositories.solver_repository import SolverRepository
from app.schemas.solver_session import SessionListResponse, SolverSessionOut

# main.py prepends /api/v1 — only the /sessions sub-prefix lives here.
router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{session_id}", response_model=SolverSessionOut)
async def get_session(
    session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    repository: SolverRepository = Depends(get_solver_repository),
) -> SolverSessionOut:
    row = await repository.get_by_id(session, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return SolverSessionOut.model_validate(row)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    problem_id: str = Query(..., description="Filter by problem_id"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    repository: SolverRepository = Depends(get_solver_repository),
) -> SessionListResponse:
    items = await repository.list_by_problem(
        session, problem_id, limit=limit, offset=offset
    )
    total = await repository.count_by_problem(session, problem_id)
    return SessionListResponse(
        items=[SolverSessionOut.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
