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

import logging
import time
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.hint.agent import HintAgent
from app.agents.hint.schemas import HintInput, HintOutput, RetrievedContext
from app.agents.verifier.schemas import RedactedTestResult
from app.core.config import Settings
from app.db.models import HintSession
from app.llm.embedding import EmbeddingService, build_failure_text
from app.repositories.hint_repository import HintRepository
from app.repositories.solver_repository import SolverRepository
from app.repositories.verifier_repository import VerifierRepository
from app.services.retrieval_service import (
    FORBIDDEN_HINT_PHRASES,
    RetrievalService,
    RetrievedFailure,
)

logger = logging.getLogger(__name__)

MAX_HINTS_PER_VERIFIER_SESSION = 5
_MAX_LEAK_CHECK_INPUTS = 5


def _find_violations(hint_text: str, failed_test_inputs: list[str]) -> list[str]:
    """Return human-readable descriptions of leaks in hint_text.

    Two leak classes:
    - input-value: a failed_test_input appears verbatim (Rule 5: don't name
      inputs or compute their answers)
    - forbidden-phrase: any of FORBIDDEN_HINT_PHRASES appears (Rules 2-3:
      no algorithm dictation in English)

    Empty list = clean. Trivially-short inputs (< 3 chars) skipped to avoid
    false positives like "0" matching "version 0.1".
    """
    violations: list[str] = []
    hint_lower = hint_text.lower()
    for inp in failed_test_inputs[:_MAX_LEAK_CHECK_INPUTS]:
        stripped = inp.strip()
        if len(stripped) < 3:
            continue
        if stripped in hint_text:
            violations.append(f"input value {stripped!r}")
    for phrase in FORBIDDEN_HINT_PHRASES:
        if phrase in hint_lower:
            violations.append(f"forbidden phrase {phrase!r}")
    return violations


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
        embedding_service: EmbeddingService,
        retrieval_service: RetrievalService,
        settings: Settings,
    ) -> None:
        self.agent = agent
        self.repository = repository
        self.verifier_repository = verifier_repository
        self.solver_repository = solver_repository
        self.embedding_service = embedding_service
        self.retrieval_service = retrieval_service
        self.settings = settings

    async def generate_and_persist(
        self,
        session: AsyncSession,
        verifier_session_id: UUID,
    ) -> tuple[HintSession, HintOutput]:
        verifier_row = await self.verifier_repository.get_by_id(session, verifier_session_id)
        if verifier_row is None:
            raise VerifierSessionNotFoundError(f"verifier_session {verifier_session_id} not found")

        if verifier_row.verified:
            raise VerifierSessionPassedError(
                f"verifier_session {verifier_session_id} already passed; no hint required"
            )

        solver_row = await self.solver_repository.get_by_id(session, verifier_row.solver_session_id)
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
                RedactedTestResult.model_validate(tr) for tr in verifier_row.test_results
            ]
        except (ValidationError, TypeError) as exc:
            raise DataIntegrityError(
                f"verifier_session {verifier_session_id} has malformed test_results: {exc}"
            ) from exc

        failed_test_inputs = [tr.input for tr in redacted_results if not tr.passed]

        retrieved: list[RetrievedFailure] = []
        if self.settings.RAG_ENABLED:
            try:
                failure_text = build_failure_text(
                    problem_text=solver_row.problem_text,
                    student_code=verifier_row.student_code,
                    failed_test_inputs=failed_test_inputs,
                    diagnosis=verifier_row.diagnosis,
                    sandbox_error=verifier_row.sandbox_error,
                )
                query_emb = await self.embedding_service.embed(failure_text)
                retrieved = await self.retrieval_service.find_similar_failures(
                    session,
                    query_embedding=query_emb,
                    exclude_verifier_session_id=verifier_session_id,
                    top_k=self.settings.RAG_TOP_K,
                    min_similarity=self.settings.RAG_MIN_SIMILARITY,
                )
                logger.info(
                    "RAG retrieved %d cases for verifier_session %s",
                    len(retrieved),
                    verifier_session_id,
                )
            except Exception as exc:
                logger.warning(
                    "RAG retrieval failed for verifier_session %s: %s. Continuing without context.",
                    verifier_session_id,
                    exc,
                )
                retrieved = []

        hint_input = HintInput(
            problem_text=solver_row.problem_text,
            student_code=verifier_row.student_code,
            failed_test_inputs=failed_test_inputs,
            prior_hints=prior_hints,
            retrieved_context=[
                RetrievedContext(
                    similarity=r.similarity,
                    past_diagnosis=r.diagnosis,
                    past_hint_texts=r.hint_texts,
                )
                for r in retrieved
            ],
        )

        # LLM generation with at-most-one regeneration when the produced hint
        # leaks an input value (Rule 5) or contains an algorithm-dictation
        # phrase from FORBIDDEN_HINT_PHRASES (Rules 2-3). RAG context makes
        # both classes more likely; the prompt rules are primary, this loop
        # is the safety net. Both classes share the single retry budget.
        # If the second attempt still leaks, log error and ship — better than
        # 500ing the user. Cost: ~1 extra LLM call per leak; baseline drift
        # measured ~33% during Step 6.2 Phase 7 smoke, so expect ~1.33 LLM
        # calls per /hint on average until the prompt is tuned further.
        start = time.perf_counter()
        output = await self.agent.generate(hint_input)
        violations = _find_violations(output.hint_text, failed_test_inputs)
        if violations:
            logger.warning(
                "Hint violations detected (attempt 1) for verifier_session %s: %s. Retrying once.",
                verifier_session_id,
                violations,
            )
            hint_input = hint_input.model_copy(
                update={
                    "regeneration_warning": (
                        f"Previous attempt violated rules: {'; '.join(violations)}. "
                        "Avoid mentioning input values OR algorithm-step language "
                        "(loops, iteration, accumulation, applying operations to "
                        "elements, etc). Stay at a conceptual level."
                    )
                }
            )
            output = await self.agent.generate(hint_input)
            violations_retry = _find_violations(output.hint_text, failed_test_inputs)
            if violations_retry:
                logger.error(
                    "Hint still violates rules after retry for verifier_session %s: %s. "
                    "Shipping anyway.",
                    verifier_session_id,
                    violations_retry,
                )
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
            f"Concurrent hint requests for verifier_session {verifier_session_id}; please retry"
        )
