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
