from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.verifier.agent import VerifierError
from app.db.session import get_db_session
from app.dependencies import get_verifier_repository, get_verifier_service
from app.repositories.verifier_repository import VerifierRepository
from app.schemas.verifier_session import (
    VerifierSessionOut,
    VerifyRequest,
    VerifyResponse,
)
from app.services.verifier_service import (
    DataIntegrityError,
    SolverSessionNotFoundError,
    VerifierService,
)

router = APIRouter(tags=["verifier"])


@router.post("/verify", response_model=VerifyResponse)
async def verify(
    request: VerifyRequest,
    service: VerifierService = Depends(get_verifier_service),
    session: AsyncSession = Depends(get_db_session),
) -> VerifyResponse:
    try:
        row, output = await service.verify_and_persist(
            session,
            request.solver_session_id,
            request.student_code,
        )
    except SolverSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DataIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="persisted solver_session has malformed test_cases",
        ) from exc
    except VerifierError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Verifier infrastructure unavailable: {exc}",
        ) from exc

    return VerifyResponse(session_id=row.id, output=output)


@router.get(
    "/verifier-sessions/{session_id}",
    response_model=VerifierSessionOut,
)
async def get_verifier_session(
    session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    repository: VerifierRepository = Depends(get_verifier_repository),
) -> VerifierSessionOut:
    row = await repository.get_by_id(session, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return VerifierSessionOut.model_validate(row)
