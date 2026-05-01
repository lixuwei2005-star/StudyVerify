"""HintService — orchestrates HintAgent + HintRepository inside one DB transaction.

Composes HintInput from the persisted verifier_session + queried prior hints
so the LLM can produce a genuinely new hint without trusting client-supplied
history. Service layer enforces:
- The MAX_HINTS_PER_VERIFIER_SESSION cap (LLM cost + answer-leak control)
- UNIQUE (verifier_session_id, hint_index) via concurrency retry on IntegrityError
- The diagnosis-seeding asymmetry: on the first hint request, the verifier's
  one-shot diagnosis is prepended to the prompt's prior_hints (so the LLM
  doesn't repeat it) but is NOT persisted as a hint row.
"""

from __future__ import annotations

import time
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.hint.agent import HintAgent
from app.agents.hint.schemas import HintInput, HintOutput
from app.agents.verifier.schemas import RedactedTestResult
from app.db.models import HintSession
from app.repositories.hint_repository import HintRepository
from app.repositories.solver_repository import SolverRepository
from app.repositories.verifier_repository import VerifierRepository

MAX_HINTS_PER_VERIFIER_SESSION = 5


class VerifierSessionNotFoundError(Exception):
    """Raised when hint request references a missing verifier_session_id, or
    when the verifier exists but its parent solver_session is missing
    (defensive — FK RESTRICT should prevent this)."""


class VerifierSessionPassedError(Exception):
    """Raised when a hint is requested for a verifier_session that already
    passed (verified=True). No hint needed."""


class HintLimitExceededError(Exception):
    """Raised when MAX_HINTS_PER_VERIFIER_SESSION hints already exist for the
    verifier_session."""


class HintConcurrencyError(Exception):
    """Raised when concurrent hint inserts race on (verifier_session_id, hint_index)
    even after a single retry."""


class DataIntegrityError(Exception):
    """Raised when persisted verifier data is malformed for hint input."""


class HintService:
    """Stateless shell. Session lifetime is owned by FastAPI's get_db_session
    dependency and passed in per call.
    """

    def __init__(
        self,
        agent: HintAgent,
        repository: HintRepository,
        verifier_repository: VerifierRepository,
        solver_repository: SolverRepository,
    ) -> None:
        self.agent = agent
        self.repository = repository
        self.verifier_repository = verifier_repository
        self.solver_repository = solver_repository

    async def generate_and_persist(
        self,
        session: AsyncSession,
        verifier_session_id: UUID,
    ) -> tuple[HintSession, HintOutput]:
        verifier_row = await self.verifier_repository.get_by_id(
            session, verifier_session_id
        )
        if verifier_row is None:
            raise VerifierSessionNotFoundError(
                f"verifier_session {verifier_session_id} not found"
            )

        if verifier_row.verified:
            raise VerifierSessionPassedError(
                f"verifier_session {verifier_session_id} already passed; "
                "no hint required"
            )

        solver_row = await self.solver_repository.get_by_id(
            session, verifier_row.solver_session_id
        )
        if solver_row is None:
            # Should be impossible due to FK RESTRICT, but defensive.
            raise VerifierSessionNotFoundError(
                "Inconsistent state: verifier exists but solver missing"
            )

        prior_hint_rows = await self.repository.list_by_verifier_session(
            session, verifier_session_id
        )
        prior_hints = [h.hint_text for h in prior_hint_rows]
        actual_prior_hint_count = await self.repository.count_by_verifier_session(
            session, verifier_session_id
        )

        # Race window: a concurrent request could push the count above the cap
        # between this check and the insert. The UNIQUE retry below catches
        # the index collision but not the over-cap case; we accept at most
        # one extra hint past the cap rather than locking the parent row.
        if actual_prior_hint_count >= MAX_HINTS_PER_VERIFIER_SESSION:
            raise HintLimitExceededError(
                f"Maximum {MAX_HINTS_PER_VERIFIER_SESSION} hints already "
                f"provided for verifier_session {verifier_session_id}. "
                "Please review the problem statement carefully or attempt "
                "a different solution."
            )

        # First-hint seeding: the verifier's one-shot diagnosis is the only
        # public feedback the student has seen. Seed it into prior_hints so
        # the LLM produces something genuinely different. Seed is for prompt
        # context only — it is NOT persisted as a hint row, and hint_index
        # is computed from the actual DB row count below.
        if not prior_hints and verifier_row.diagnosis:
            prior_hints = [verifier_row.diagnosis]

        try:
            redacted_results = [
                RedactedTestResult.model_validate(tr)
                for tr in verifier_row.test_results
            ]
        except (ValidationError, TypeError) as exc:
            raise DataIntegrityError(
                f"verifier_session {verifier_session_id} has malformed "
                f"test_results: {exc}"
            ) from exc

        failed_test_inputs = [
            tr.input for tr in redacted_results if not tr.passed
        ]

        hint_input = HintInput(
            problem_text=solver_row.problem_text,
            student_code=verifier_row.student_code,
            failed_test_inputs=failed_test_inputs,
            prior_hints=prior_hints,
        )

        start = time.perf_counter()
        output = await self.agent.generate(hint_input)
        total_latency_ms = int((time.perf_counter() - start) * 1000)
        # llm_prior_hints_count records what the LLM actually saw, including
        # the seeded diagnosis if any. Persisted alongside the hint as
        # provenance; distinct from hint_index (the Nth real hint row).
        llm_prior_hints_count = len(prior_hints)
        output_hint_index = actual_prior_hint_count + 1

        # UNIQUE (verifier_session_id, hint_index) protects against concurrent
        # inserts that compute the same next index. On collision, refetch the
        # actual row count and retry once with a fresh index — do NOT call
        # the LLM again; the race is on insert, not generation.
        for attempt in range(2):
            try:
                row = await self.repository.create(
                    session,
                    verifier_session_id=verifier_session_id,
                    hint_index=output_hint_index,
                    hint_text=output.hint_text,
                    prior_hints_count=llm_prior_hints_count,
                    total_latency_ms=total_latency_ms,
                )
                await session.commit()
                await session.refresh(row)
                return row, output
            except IntegrityError:
                await session.rollback()
                if attempt == 1:
                    raise HintConcurrencyError(
                        "Concurrent hint requests for verifier_session "
                        f"{verifier_session_id}; please retry"
                    )

                prior_hint_rows = await self.repository.list_by_verifier_session(
                    session, verifier_session_id
                )
                output_hint_index = len(prior_hint_rows) + 1

        # Defensive — the loop body always returns or raises.
        raise HintConcurrencyError(
            "Concurrent hint requests for verifier_session "
            f"{verifier_session_id}; please retry"
        )
