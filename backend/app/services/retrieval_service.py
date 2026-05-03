"""Similarity retrieval over verifier_sessions.failure_embedding (Step 6.2).

Reads only — no writes, no commits. Returns past failed verifier sessions
ranked by cosine similarity to the query embedding, joined with their
already-given hints.

Past hints are sanitized via `filter_dangerous_hints` BEFORE being passed
to HintAgent. The sanitization layer is independent from the prompt-layer
inspiration-only rule: spec rule "Do not trust prompt wording alone for
retrieved hint safety" requires both guards.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Mirrors the algorithm-dictation list called out in
# `app/agents/hint/prompts.py` (Step 5.1). Copied explicitly rather than
# imported because the prompts module embeds these as English in the system
# prompt — they aren't a structured constant there. Keep this list in sync if
# the hint prompt rules change.
#
# The second group of phrases (12-23) was added in Step 6.2 Phase 7 after RAG
# context biased LLM hints toward algorithm-specific English. The first leak
# observed was "What single arithmetic operation can you apply to each element
# to gradually build up the final total?" — which dictates loop + accumulate
# in plain English. These additional phrases catch that drift pattern.
FORBIDDEN_HINT_PHRASES: tuple[str, ...] = (
    # Original Step 5.1 set (12 phrases)
    "create a variable",
    "loop through",
    "loop over",
    "iterate through",
    "iterate over",
    "for each element",
    "running total",
    "accumulate",
    "examine each element",
    "return that variable",
    "after the loop",
    "combine the values",
    # Step 6.2 Phase 7 RAG-drift extensions (12 phrases)
    "apply to each element",
    "apply to every element",
    "build up",
    "gradually build",
    "final total",
    "single operation",
    "single arithmetic operation",
    "step by step",
    "consider each element",
    "process each element",
    "for every item",
    "for every element",
)
MAX_RETRIEVED_HINT_CHARS = 300


@dataclass(frozen=True)
class RetrievedFailure:
    verifier_session_id: UUID
    similarity: float
    diagnosis: str
    hint_texts: list[str]


def _is_dangerous_hint(text_value: str) -> bool:
    lowered = text_value.lower()
    return any(phrase in lowered for phrase in FORBIDDEN_HINT_PHRASES)


def _cap_hint(text_value: str) -> str:
    text_value = text_value.strip()
    if len(text_value) <= MAX_RETRIEVED_HINT_CHARS:
        return text_value
    return text_value[: MAX_RETRIEVED_HINT_CHARS - 3] + "..."


def filter_dangerous_hints(retrieved: list[RetrievedFailure]) -> list[RetrievedFailure]:
    """Drop hint_texts that contain algorithm-dictation phrases; keep the case.

    Case-insensitive substring match. Cap remaining hints at
    MAX_RETRIEVED_HINT_CHARS. A retrieved case with all hints filtered out is
    still returned — the diagnosis alone is useful inspiration for the agent.
    """
    filtered: list[RetrievedFailure] = []
    for item in retrieved:
        safe_hints = [
            _cap_hint(hint) for hint in item.hint_texts if hint and not _is_dangerous_hint(hint)
        ]
        filtered.append(
            RetrievedFailure(
                verifier_session_id=item.verifier_session_id,
                similarity=item.similarity,
                diagnosis=item.diagnosis,
                hint_texts=safe_hints,
            )
        )
    return filtered


_SIMILARITY_SQL = text(
    """
    SELECT
        v.id,
        1 - (v.failure_embedding <=> CAST(:query_emb AS vector)) AS similarity,
        v.diagnosis,
        COALESCE(
            array_agg(h.hint_text ORDER BY h.hint_index)
                FILTER (WHERE h.hint_text IS NOT NULL),
            ARRAY[]::text[]
        ) AS hint_texts
    FROM verifier_sessions v
    LEFT JOIN hint_sessions h ON h.verifier_session_id = v.id
    WHERE v.failure_embedding IS NOT NULL
      AND v.embedding_status = 'success'
      AND v.verified = false
      AND (CAST(:exclude AS uuid) IS NULL OR v.id <> CAST(:exclude AS uuid))
    GROUP BY v.id, v.failure_embedding, v.diagnosis
    HAVING 1 - (v.failure_embedding <=> CAST(:query_emb AS vector)) >= :min_sim
    ORDER BY v.failure_embedding <=> CAST(:query_emb AS vector)
    LIMIT :top_k
    """
)


class RetrievalService:
    """Reads only. No writes, no commits."""

    async def find_similar_failures(
        self,
        session: AsyncSession,
        *,
        query_embedding: list[float],
        exclude_verifier_session_id: UUID | None = None,
        top_k: int = 3,
        min_similarity: float = 0.7,
    ) -> list[RetrievedFailure]:
        result = await session.execute(
            _SIMILARITY_SQL,
            {
                "query_emb": str(query_embedding),
                "exclude": str(exclude_verifier_session_id)
                if exclude_verifier_session_id
                else None,
                "min_sim": min_similarity,
                "top_k": top_k,
            },
        )

        raw = [
            RetrievedFailure(
                verifier_session_id=row.id,
                similarity=float(row.similarity),
                diagnosis=row.diagnosis or "",
                hint_texts=list(row.hint_texts) if row.hint_texts else [],
            )
            for row in result
        ]
        return filter_dangerous_hints(raw)
