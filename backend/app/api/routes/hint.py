from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.dependencies import get_hint_repository, get_hint_service
from app.repositories.hint_repository import HintRepository
from app.schemas.hint_session import HintRequest, HintResponse, HintSessionOut
from app.services.hint_service import (
    DataIntegrityError,
    HintConcurrencyError,
    HintLimitExceededError,
    HintService,
    VerifierSessionNotFoundError,
    VerifierSessionPassedError,
)

router = APIRouter(tags=["hint"])


@router.post("/hint", response_model=HintResponse)
async def request_hint(
    request: HintRequest,
    service: HintService = Depends(get_hint_service),
    session: AsyncSession = Depends(get_db_session),
) -> HintResponse:
    try:
        row, output = await service.generate_and_persist(
            session, request.verifier_session_id
        )
    except VerifierSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except VerifierSessionPassedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except HintConcurrencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except HintLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    except DataIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    return HintResponse(
        session_id=row.id,
        hint_index=row.hint_index,
        hint_text=output.hint_text,
    )


@router.get(
    "/hint-sessions/{session_id}",
    response_model=HintSessionOut,
)
async def get_hint_session(
    session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    repository: HintRepository = Depends(get_hint_repository),
) -> HintSessionOut:
    row = await repository.get_by_id(session, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return HintSessionOut.model_validate(row)
