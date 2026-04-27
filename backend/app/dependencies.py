"""FastAPI dependency factories shared across routes.

Centralizes wiring so route modules don't each import construction logic.
Repository is cached (stateless), Service is not (constructor is trivial,
leaving room for future per-request state).
"""

from functools import lru_cache

from fastapi import Depends

from app.agents.solver.agent import SolverAgent, get_solver_agent
from app.repositories.solver_repository import SolverRepository
from app.services.solver_service import SolverService


@lru_cache
def get_solver_repository() -> SolverRepository:
    return SolverRepository()


def get_solver_service(
    agent: SolverAgent = Depends(get_solver_agent),
    repository: SolverRepository = Depends(get_solver_repository),
) -> SolverService:
    return SolverService(agent=agent, repository=repository)
