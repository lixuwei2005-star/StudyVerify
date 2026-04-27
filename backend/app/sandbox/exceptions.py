class SandboxError(Exception):
    """Raised when the sandbox runner cannot execute user code at all."""


class SandboxTimeoutError(SandboxError):
    """Raised when subprocess exceeds its wall-clock timeout."""
