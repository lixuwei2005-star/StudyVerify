"""FastAPI dependency factories shared across routes.

Centralizes wiring so route modules don't each import construction logic.
Repository is cached (stateless), Service is not (constructor is trivial,
leaving room for future per-request state).
"""

from functools import lru_cache

from fastapi import Depends

from app.agents.hint.agent import HintAgent, get_hint_agent
from app.agents.solver.agent import SolverAgent, get_solver_agent
from app.agents.verifier.agent import VerifierAgent, get_verifier_agent
from app.core.config import get_settings
from app.llm.embedding import EmbeddingService
from app.repositories.hint_repository import HintRepository
from app.repositories.solver_repository import SolverRepository
from app.repositories.verifier_repository import VerifierRepository
from app.services.hint_service import HintService
from app.services.retrieval_service import RetrievalService
from app.services.solver_service import SolverService
from app.services.verifier_service import VerifierService


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(get_settings())


@lru_cache
def get_retrieval_service() -> RetrievalService:
    return RetrievalService()


@lru_cache
def get_solver_repository() -> SolverRepository:
    return SolverRepository()


def get_solver_service(
    agent: SolverAgent = Depends(get_solver_agent),
    repository: SolverRepository = Depends(get_solver_repository),
) -> SolverService:
    return SolverService(agent=agent, repository=repository)


@lru_cache
def get_verifier_repository() -> VerifierRepository:
    return VerifierRepository()


def get_verifier_service(
    agent: VerifierAgent = Depends(get_verifier_agent),
    repository: VerifierRepository = Depends(get_verifier_repository),
    solver_repository: SolverRepository = Depends(get_solver_repository),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
) -> VerifierService:
    return VerifierService(
        agent=agent,
        repository=repository,
        solver_repository=solver_repository,
        embedding_service=embedding_service,
    )


@lru_cache
def get_hint_repository() -> HintRepository:
    return HintRepository()


def get_hint_service(
    agent: HintAgent = Depends(get_hint_agent),
    repository: HintRepository = Depends(get_hint_repository),
    verifier_repository: VerifierRepository = Depends(get_verifier_repository),
    solver_repository: SolverRepository = Depends(get_solver_repository),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
) -> HintService:
    return HintService(
        agent=agent,
        repository=repository,
        verifier_repository=verifier_repository,
        solver_repository=solver_repository,
        embedding_service=embedding_service,
        retrieval_service=retrieval_service,
        settings=get_settings(),
    )
