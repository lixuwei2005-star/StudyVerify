# StudyVerify - Step 6.1: LLM Gateway + OpenAI Fallback Spec

## Goal
Abstract the current hardcoded `DeepSeekClient` into a provider-pluggable
`LLMGateway` with retry + cross-provider fallback. Add OpenAI as fallback
provider. After this step, single-vendor outage should not break the product.

The gateway must be stateless and transparent to Agents: existing agent call
patterns keep working through `get_llm_client().chat(...)`.

## Why This Step
Today every Agent imports or receives a DeepSeek-shaped client directly.
DeepSeek hiccup -> solve / hint / verify LLM paths can degrade or fail.

Production-grade fallback is standard for LLM-driven services. OpenAI is
geographically and organizationally independent of DeepSeek, so a both-down
event is much less likely than a single-provider outage.

## Scope
- New `LLMProvider` Protocol (interface contract)
- Refactor existing `DeepSeekClient` -> `DeepSeekProvider`
- Preserve `DeepSeekClient = DeepSeekProvider` as a compatibility alias
- New `OpenAIProvider` (implements Protocol; messages format is
  OpenAI-compatible)
- New `LLMGateway` class: primary + fallback + retry orchestration
- DI: `get_llm_client()` now returns `LLMGateway`, but `.chat(...)` signature is
  unchanged for Agents
- Settings add `OPENAI_API_KEY`, `OPENAI_MODEL`, `LLM_FALLBACK_ENABLED`, and
  `LLM_FALLBACK_PROVIDER`
- New `sanitize_error_message(...)` helper for provider error text

## Out of Scope
- Per-Agent provider selection - all Agents use the same gateway config
- Anthropic / Gemini / other providers - only DeepSeek + OpenAI
- Cost tracking / usage logging - Step 9 territory
- Provider-specific prompt tuning - same prompts for both providers
- RAG context injection - Step 6.2
- LangGraph orchestration - Step 6.3
- 4xx vs 5xx retry classification - documented as Step 9 hardening below

## Architecture

```text
Agent.chat(messages, model, temperature, json_mode)
   |
   v
LLMGateway.chat(messages, model, temperature, json_mode)
   |
   +-- Try primary (DeepSeek):
   |     Attempt 1 -> response or LLMError
   |     Attempt 2 after 0.5s -> response or LLMError
   |     Attempt 3 after 1.0s -> response or LLMError
   |
   +-- If LLM_FALLBACK_ENABLED=False:
   |     Raise the original primary error
   |
   +-- Try fallback (OpenAI, if configured):
         Attempt 1 -> response or LLMError
         Attempt 2 after 0.5s -> response or LLMError
         Attempt 3 after 1.0s -> response or LLMError
         If still failing -> raise LLMAllProvidersFailedError
```

Notes:
- Gateway is stateless. A single cached instance serves concurrent requests.
- Gateway owns retry. Providers do exactly one native call per `.chat(...)`.
- Each provider owns native client construction and native exception ->
  `LLMError` / `LLMTimeoutError` translation.
- Gateway retry against the same provider catches transient request-level
  errors. Fallback catches persistent provider-level outage.

## File Layout

### New
- `backend/app/llm/providers/__init__.py`
- `backend/app/llm/providers/base.py` - `ChatMessage` TypedDict +
  `LLMProvider` Protocol
- `backend/app/llm/providers/deepseek.py` - `DeepSeekProvider` refactored from
  current `client.py`, with internal retry removed
- `backend/app/llm/providers/openai.py` - `OpenAIProvider`
- `backend/app/llm/gateway.py` - `LLMGateway` class + `get_llm_gateway()`
- `backend/app/llm/sanitize.py` - provider error sanitization helper
- `backend/tests/llm/test_gateway.py` - gateway unit tests
- `backend/tests/llm/test_openai_provider.py` - OpenAI integration tests
- `backend/tests/llm/test_gateway_fallback_integration.py` - real fallback
  scenario

### Modified
- `backend/app/llm/client.py` - keep file. Add re-export alias
  `DeepSeekClient = DeepSeekProvider`. Existing `get_llm_client()` is
  repurposed to return `LLMGateway`, which still has `.chat()` with the same
  signature, so Agents are zero-change.
- `backend/app/llm/__init__.py` - export both `DeepSeekProvider` and
  `DeepSeekClient` if explicit exports remain.
- `backend/app/llm/exceptions.py` - add `LLMAllProvidersFailedError`.
- `backend/app/core/config.py` - add `OPENAI_API_KEY`, `OPENAI_MODEL`,
  `LLM_FALLBACK_ENABLED`, `LLM_FALLBACK_PROVIDER`.
- `backend/.env.example` - add fallback config examples.

## LLMProvider Protocol

```python
# app/llm/providers/base.py

from typing import Literal, Protocol, TypedDict


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMProvider(Protocol):
    """All providers expose the same chat interface used by Agents.

    Implementation contract:
    - Native API errors are translated to LLMError or LLMTimeoutError.
    - chat() is async and returns the assistant's text response.
    - messages format is OpenAI-compatible.
    - Providers MUST handle provider-specific request shapes internally.
    - Gateway and Agent code does not see provider-specific shapes.

    The `model` kwarg is provider-specific. If passed, it overrides the
    provider's default model. Cross-provider model names won't match - passing
    model="gpt-4o-mini" to DeepSeekProvider will fail at the provider's API.
    Callers passing `model` are coupling to a specific provider.
    """

    name: str

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str:
        ...
```

Existing agents pass dicts that conform to this shape. `TypedDict` is
structural, so there is no runtime breakage; mypy will catch drift at
static-check time.

## DeepSeekProvider

Move existing `backend/app/llm/client.py` provider logic to
`backend/app/llm/providers/deepseek.py`. Rename the class to
`DeepSeekProvider`, add `name = "deepseek"`, and keep the public `.chat()`
signature exactly aligned with the current `DeepSeekClient.chat(...)` surface:

```python
async def chat(
    self,
    messages: list[ChatMessage],
    model: str | None = None,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str:
    ...
```

Provider behavior:
- Use `model` if passed; otherwise use `settings.DEEPSEEK_MODEL`.
- Preserve `settings.DEEPSEEK_REASONING_EFFORT` behavior.
- Do exactly one native HTTP call.
- Translate native OpenAI-compatible SDK errors into `LLMError`,
  `LLMRateLimitError`, or `LLMTimeoutError`.
- Do not sleep or retry inside the provider.

## DeepSeekClient Compatibility Alias

The rename `DeepSeekClient -> DeepSeekProvider` breaks existing imports unless
the old name remains available. Current references include:
- `backend/app/agents/solver/agent.py`
- `backend/app/agents/hint/agent.py`
- `backend/app/agents/verifier/agent.py`
- Agent tests using `AsyncMock(spec=DeepSeekClient)`

Keep `backend/app/llm/client.py` as the compatibility entrypoint:

```python
# app/llm/client.py

from app.llm.gateway import get_llm_gateway
from app.llm.providers.deepseek import DeepSeekProvider

DeepSeekClient = DeepSeekProvider  # compatibility alias

# Backward-compatible DI name. Existing code calls get_llm_client().
get_llm_client = get_llm_gateway
```

If `backend/app/llm/__init__.py` has explicit exports, export both names:

```python
from app.llm.client import DeepSeekClient, get_llm_client
from app.llm.providers.deepseek import DeepSeekProvider

__all__ = [
    "DeepSeekClient",
    "DeepSeekProvider",
    "get_llm_client",
    ...
]
```

## OpenAIProvider

`openai` is already installed in this repo (`openai>=2.32.0` in
`backend/pyproject.toml` and locked at 2.32.0). Confirm by checking
`pyproject.toml` and `uv tree | grep openai`; no `uv add` is needed.

OpenAI 2.x compatibility notes to verify during implementation:
- `AsyncOpenAI` still exists.
- `APIError` and `APITimeoutError` are still available from `openai`.
- `response.choices[0].message.content` remains valid for chat completions.
- If any SDK shape drift appears, adjust this provider to match the installed
  2.x SDK rather than old 1.x examples.

```python
# app/llm/providers/openai.py

import logging

from openai import APIError, APITimeoutError, AsyncOpenAI

from app.core.config import Settings
from app.llm.exceptions import LLMError, LLMTimeoutError
from app.llm.providers.base import ChatMessage

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """OpenAI provider. Uses settings.OPENAI_MODEL by default."""

    name = "openai"

    def __init__(self, settings: Settings):
        if not settings.OPENAI_API_KEY:
            raise ValueError(
                "OpenAI provider initialized without API key. "
                "Set OPENAI_API_KEY or disable fallback."
            )
        self._client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self._model = settings.OPENAI_MODEL

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str:
        model_name = model or self._model
        kwargs = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except APITimeoutError as exc:
            raise LLMTimeoutError("OpenAI timed out") from exc
        except APIError as exc:
            raise LLMError(f"OpenAI API error: {exc}") from exc

        if not response.choices or not response.choices[0].message.content:
            raise LLMError("OpenAI returned empty response")

        return response.choices[0].message.content
```

## Sanitizing Provider Errors

Provider exception strings can sometimes include request details, malformed
headers, or embedded credentials. Before logging or returning provider error
text, redact known secret patterns.

```python
# app/llm/sanitize.py

import re


_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_.\-]{20,}"),
    re.compile(
        r"api[_-]?key[\"':=\s]+[A-Za-z0-9_.\-]{20,}",
        re.IGNORECASE,
    ),
]


def sanitize_error_message(message: str) -> str:
    """Redact known secret patterns from error text before logging or returning.

    Best-effort; not cryptographic. Defends against accidental SDK errors that
    echo back an auth header or URL with embedded credentials.
    """
    sanitized = message
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized
```

Gateway logs and `LLMAllProvidersFailedError` detail must use sanitized strings.

## LLMGateway

```python
# app/llm/gateway.py

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.llm.exceptions import LLMAllProvidersFailedError, LLMError, LLMTimeoutError
from app.llm.providers.base import ChatMessage, LLMProvider
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.openai import OpenAIProvider
from app.llm.sanitize import sanitize_error_message

logger = logging.getLogger(__name__)

MAX_ATTEMPTS_PER_PROVIDER = 3
BACKOFF_BASE_SECONDS = 0.5


class LLMGateway:
    """Routes chat() calls through primary -> fallback chain.

    Each provider gets up to MAX_ATTEMPTS_PER_PROVIDER total attempts. After
    primary is exhausted, the gateway falls through to fallback if configured.
    If all providers fail, raises LLMAllProvidersFailedError.

    Stateless. One cached instance serves concurrent requests.
    """

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider | None,
        fallback_enabled: bool,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._fallback_enabled = fallback_enabled and fallback is not None

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str:
        primary_error: Exception | None = None

        try:
            return await self._call_with_retry(
                self._primary,
                messages,
                model,
                temperature,
                json_mode,
            )
        except (LLMError, LLMTimeoutError) as exc:
            primary_error = exc
            logger.warning(
                "Primary provider %s exhausted retries: %s",
                self._primary.name,
                sanitize_error_message(str(exc)),
            )

        if not self._fallback_enabled:
            raise primary_error  # type: ignore[misc]

        assert self._fallback is not None
        try:
            logger.info("Falling back from %s to %s", self._primary.name, self._fallback.name)
            return await self._call_with_retry(
                self._fallback,
                messages,
                model,
                temperature,
                json_mode,
            )
        except (LLMError, LLMTimeoutError) as fallback_error:
            logger.error(
                "Fallback provider %s also failed: %s",
                self._fallback.name,
                sanitize_error_message(str(fallback_error)),
            )
            raise LLMAllProvidersFailedError(
                f"Primary ({self._primary.name}) failed: "
                f"{sanitize_error_message(str(primary_error))}; "
                f"Fallback ({self._fallback.name}) failed: "
                f"{sanitize_error_message(str(fallback_error))}"
            ) from fallback_error

    async def _call_with_retry(
        self,
        provider: LLMProvider,
        messages: list[ChatMessage],
        model: str | None,
        temperature: float,
        json_mode: bool,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS_PER_PROVIDER):
            try:
                return await provider.chat(
                    messages,
                    model=model,
                    temperature=temperature,
                    json_mode=json_mode,
                )
            except (LLMError, LLMTimeoutError) as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS_PER_PROVIDER - 1:
                    backoff = BACKOFF_BASE_SECONDS * (2**attempt)
                    logger.warning(
                        "%s attempt %d/%d failed, retrying in %.1fs: %s",
                        provider.name,
                        attempt + 1,
                        MAX_ATTEMPTS_PER_PROVIDER,
                        backoff,
                        sanitize_error_message(str(exc)),
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise
        raise last_error  # type: ignore[misc]


@lru_cache
def get_llm_gateway() -> LLMGateway:
    settings = get_settings()
    primary = DeepSeekProvider(settings)

    fallback: LLMProvider | None = None

    if settings.LLM_FALLBACK_ENABLED:
        if settings.LLM_FALLBACK_PROVIDER != "openai":
            raise ValueError(
                f"LLM_FALLBACK_ENABLED=true but "
                f"LLM_FALLBACK_PROVIDER={settings.LLM_FALLBACK_PROVIDER!r} "
                "is not supported. Use 'openai' or set "
                "LLM_FALLBACK_ENABLED=false."
            )
        if not settings.OPENAI_API_KEY:
            raise ValueError(
                "LLM_FALLBACK_ENABLED=true but OPENAI_API_KEY is empty. "
                "Either set OPENAI_API_KEY or set LLM_FALLBACK_ENABLED=false "
                "in your .env."
            )
        fallback = OpenAIProvider(settings)

    return LLMGateway(
        primary=primary,
        fallback=fallback,
        fallback_enabled=fallback is not None,
    )
```

### Retry Ownership

Gateway owns retry. Provider implementations do exactly one native call.

The current `DeepSeekClient` retry loop used `settings.LLM_MAX_RETRIES`, with
default `3` total attempts. If that loop remains inside `DeepSeekProvider` and
gateway retry is added above it, one primary failure can trigger nested retries:
`3 gateway attempts * 3 provider attempts = 9 native calls` before fallback.
That is too much latency and can blow rate limits.

For Step 6.1:
- Remove provider retry loops.
- Set `MAX_ATTEMPTS_PER_PROVIDER = 3`.
- Use gateway-level backoff: `0.5s`, then `1.0s`, then final failure.
- Document 4xx non-retry classification as future Step 9 hardening.

## Settings Update

```python
# app/core/config.py

class Settings(BaseSettings):
    # ... existing fields ...

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    LLM_FALLBACK_ENABLED: bool = False
    LLM_FALLBACK_PROVIDER: str = "openai"
```

`.env.example` add:

```dotenv
# Optional OpenAI fallback provider. Disabled by default.
# To enable fallback, set both LLM_FALLBACK_ENABLED=true and OPENAI_API_KEY.
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
LLM_FALLBACK_ENABLED=false
LLM_FALLBACK_PROVIDER=openai
```

### Misconfigured Fallback

Silent fallback-disabled behavior is a footgun: operators see "fallback
enabled" in config but still get a 503 when DeepSeek hiccups. Loud failure at
startup forces correct config or explicit opt-out.

Rules:
- `LLM_FALLBACK_ENABLED=false`, `OPENAI_API_KEY=""` -> gateway constructs with
  `fallback=None`.
- `LLM_FALLBACK_ENABLED=true`, `OPENAI_API_KEY=""` -> `get_llm_gateway()`
  raises `ValueError`.
- `LLM_FALLBACK_ENABLED=true`, unsupported `LLM_FALLBACK_PROVIDER` ->
  `get_llm_gateway()` raises `ValueError`.

## Exceptions Update

```python
# app/llm/exceptions.py

class LLMAllProvidersFailedError(LLMError):
    """Raised when both primary and fallback providers fail."""
```

## Tests

### Unit (`tests/llm/test_gateway.py`, 20 tests)

1. **happy_path_primary_succeeds**: primary `.chat()` returns text on first call
   -> no fallback invoked.
2. **primary_transient_error_retries_then_succeeds**: primary raises
   `LLMTimeoutError` once, succeeds on retry -> fallback not invoked.
3. **primary_persistent_error_falls_back**: primary raises all 3 attempts,
   fallback succeeds -> returned response from fallback.
4. **fallback_disabled_propagates_primary_error**: fallback disabled, primary
   fails 3 times -> raises original `LLMError`, not
   `LLMAllProvidersFailedError`.
5. **all_providers_fail_raises_combined_error**: both fail -> raises
   `LLMAllProvidersFailedError` with provider names and sanitized error detail.
6. **fallback_retries_independently**: primary fails 3 times, fallback fails
   once then succeeds -> 5 total provider calls.
7. **temperature_and_json_mode_passed_through**: gateway passes kwargs to
   provider unchanged.
8. **logging_includes_provider_names**: `caplog` asserts warnings include
   `deepseek` on primary failure and fallback logs include `openai`.
9. **stateless_concurrent_safe**: invoke `gateway.chat` from multiple concurrent
   tasks; assert no shared state corruption.
10. **fallback_success_does_not_raise_all_providers_error**: primary exhausted,
    fallback succeeds -> no combined error.
11. **test_model_kwarg_passthrough**: `gateway.chat(messages,
    model="gpt-4o-mini")` -> provider receives `model="gpt-4o-mini"`.
12. **test_deepseek_client_compat_alias_imports**: `from app.llm.client import
    DeepSeekClient`; assert `DeepSeekClient is DeepSeekProvider`;
    `AsyncMock(spec=DeepSeekClient)` constructs successfully.
13. **test_no_double_retry**: mocked primary raises persistent `LLMError`; assert
    primary called exactly 3 times and fallback called exactly 3 times, not 6 or
    9.
14. **test_backoff_between_retries**: mock `asyncio.sleep`; provider raises 3x;
    assert sleep calls are `[0.5, 1.0]` and no sleep after final failure.
15. **test_misconfigured_fallback_raises_at_startup**:
    `LLM_FALLBACK_ENABLED=true`, `OPENAI_API_KEY=""` -> `get_llm_gateway()`
    raises `ValueError`; message mentions both `LLM_FALLBACK_ENABLED` and
    `OPENAI_API_KEY`.
16. **test_fallback_disabled_no_openai_key_works**:
    `LLM_FALLBACK_ENABLED=false`, `OPENAI_API_KEY=""` -> gateway constructs,
    fallback is `None`.
17. **test_sanitize_redacts_api_keys**: `sanitize_error_message` redacts
    `sk-...`, `Bearer ...`, and `api_key=...`.
18. **test_combined_error_sanitized**: all-providers-fail error does not contain
    raw secrets from provider exceptions.
19. **test_existing_agents_still_work_with_mock_spec**:
    `AsyncMock(spec=DeepSeekClient)` supports real solver/verifier/hint call
    patterns.
20. **test_get_llm_gateway_lru_cache_clearable**: `get_llm_gateway()` returns
    the same instance twice; `get_llm_gateway.cache_clear()` makes the next call
    return a new instance for tests that override settings.

### Provider Unit Tests

`tests/llm/test_deepseek_provider.py`:
- One native SDK call per `.chat(...)`; no provider retry.
- `model` kwarg overrides `settings.DEEPSEEK_MODEL`.
- `json_mode=True` adds `response_format={"type": "json_object"}`.
- `DEEPSEEK_REASONING_EFFORT != "none"` adds `extra_body`.
- Timeout, rate-limit, transport, and status exceptions map to existing typed
  `LLMError` subclasses.

`tests/llm/test_openai_provider.py`:
- One native SDK call per `.chat(...)`; no provider retry.
- `model` kwarg overrides `settings.OPENAI_MODEL`.
- `json_mode=True` adds `response_format={"type": "json_object"}`.
- Empty response raises `LLMError`.
- Timeout maps to `LLMTimeoutError`.

### Integration Tests (real APIs, gated)

`tests/llm/test_openai_provider.py` with `@pytest.mark.integration`, skip if
`OPENAI_API_KEY` unset:
1. **real_chat_returns_text**: simple prompt, assert non-empty response.
2. **json_mode_returns_valid_json**: prompt for JSON object, assert
   `json.loads` succeeds.
3. **timeout_raises_LLMTimeoutError**: artificially short timeout on client ->
   `LLMTimeoutError`.

`tests/llm/test_gateway_fallback_integration.py` with integration gates:
1. **real_primary_succeeds_no_fallback_call**: with both keys configured,
   primary DeepSeek succeeds; logs show no fallback invocation.
2. **simulated_primary_failure_falls_back_to_openai**: monkeypatch
   `DeepSeekProvider.chat` to raise `LLMError`; gateway falls back to real
   OpenAI; assert non-empty response. This is the acceptance test for Step 6.1.

## Verification

1. Unit tests: 20 gateway tests passed, plus provider unit tests.
2. Integration: 3 OpenAI + 2 fallback = 5 passed when both keys are set.
3. Full regression: existing suite passes with new LLM gateway tests.
4. End-to-end smoke: existing smoke should pass unchanged because gateway is
   transparent to Agents.
5. Manual fallback drill:
   - Set `LLM_FALLBACK_ENABLED=true` and valid `OPENAI_API_KEY`.
   - Temporarily set `DEEPSEEK_API_KEY=invalid`.
   - Restart API and run smoke.
   - Expect log "Primary provider deepseek exhausted retries".
   - Expect log "Falling back from deepseek to openai".
   - Smoke remains green, slightly slower.
   - Restore correct `DEEPSEEK_API_KEY`.

## What NOT To Do

- DO NOT remove the `DeepSeekClient` compatibility alias. Three Agents and
  their tests reference it by name. Removing it is a separate breaking change.
- DO NOT keep retry loops inside provider implementations. Gateway owns retry.
  Providers do exactly one native call. Double retry means 6+ requests per
  failure event, blown latency, and blown rate limits.
- DO NOT call the fallback provider when primary succeeds. Primary success
  means 1 provider call total.
- DO NOT swallow `LLMAllProvidersFailedError` in Agents. It should bubble up to
  the route handler as an LLM failure.
- DO NOT log full message content. Log provider name, attempt number, sanitized
  error text, and error type only.
- DO NOT return raw provider exception text without `sanitize_error_message`.
- DO NOT introduce circuit breaker / health check / cooldown in this step.
  Retry-then-fallback covers the current scale; circuit breaker is Step 9+
  territory if needed.
- DO NOT add provider-specific prompt tuning here. Same prompts for both
  providers; quality differences belong in Step 9 evaluation data.

## Future Hardening (Step 9)

Current implementation retries on any `(LLMError, LLMTimeoutError)` uniformly.
In production, 4xx errors (auth, malformed prompt) SHOULD NOT retry because
they are persistent and waste cost. 5xx and timeouts SHOULD retry.

Step 9 hardening: classify exceptions by HTTP status when available. Skip retry
for 4xx, retry 5xx + timeouts. This requires provider-specific exception
inspection because DeepSeek and OpenAI may expose status differently.

For 6.1 we accept the slight waste on 4xx because:
1. 4xx errors are usually configuration bugs caught in development.
2. Production should not see frequent 4xx unless API keys rotate; loud
   startup failure catches missing fallback keys earlier.
3. Retry budget cap (`3 attempts * short backoff`) limits worst-case cost.

## Estimated Time

- Provider Protocol + DeepSeek refactor (drop internal retry): 45 min
- OpenAI provider (verify 2.x SDK compatibility): 30 min
- Gateway with retry + backoff + sanitization: 45 min
- Settings + `.env.example` + DI factory + loud failure: 25 min
- Unit tests (20 tests now, was 10): 75 min
- Integration tests (5): 45 min (real LLM calls, cannot speed up)
- Manual fallback drill + smoke: 15 min
- ruff + mypy + ensure `DeepSeekClient` compat works: 15 min
- Total: ~4.5 hours

## Critical Pre-implementation Check

1. Read `backend/app/llm/client.py`; the new Protocol must match the real
   `DeepSeekClient.chat(...)` signature, including `model`.
2. Read `backend/app/core/config.py`; this repo's settings object lives in the
   config module, not in a separate settings module.
3. Read `backend/.env.example`; preserve the existing env-file style.
4. Confirm `openai` is already installed at 2.32.0 via `backend/pyproject.toml`
   and `backend/uv.lock`; no dependency add should be required.
5. Grep for direct `DeepSeekClient` imports and keep the compatibility alias
   until those annotations and tests are intentionally migrated.
6. Verify provider retry loops are removed before gateway retry is added.
