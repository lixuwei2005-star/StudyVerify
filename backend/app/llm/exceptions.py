class LLMError(Exception):
    """Base error for any LLM provider failure surfaced to callers."""


class LLMTimeoutError(LLMError):
    """Raised when the LLM call exceeds the configured timeout."""


class LLMRateLimitError(LLMError):
    """Raised when the LLM provider rate-limits us beyond our retry budget."""


class LLMAllProvidersFailedError(LLMError):
    """Raised when both primary and fallback providers fail."""
