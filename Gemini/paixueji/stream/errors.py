"""Helpers for recognizing and surfacing rate-limit failures."""

DEFAULT_RATE_LIMIT_USER_MESSAGE = (
    "The model is busy right now, so there was no answer to show. "
    "Please try again in a moment."
)


class RateLimitError(RuntimeError):
    """Raised when the upstream model returns a rate-limit failure."""

    def __init__(self, message: str, user_message: str = DEFAULT_RATE_LIMIT_USER_MESSAGE):
        super().__init__(message)
        self.code = 429
        self.error_type = "rate_limited"
        self.user_message = user_message

    def to_payload(self) -> dict:
        return {
            "code": self.code,
            "error_type": self.error_type,
            "message": str(self),
            "user_message": self.user_message,
        }


def is_rate_limit_error(exc: BaseException) -> bool:
    """Best-effort detection for Gemini 429 / RESOURCE_EXHAUSTED errors."""
    if isinstance(exc, RateLimitError):
        return True

    for attr_name in ("code", "status_code"):
        if getattr(exc, attr_name, None) == 429:
            return True

    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) == 429:
        return True

    text = str(exc).upper()
    return (
        "429" in text
        or "RESOURCE_EXHAUSTED" in text
        or "TOO MANY REQUESTS" in text
        or "RATE LIMIT" in text
    )


def as_rate_limit_error(exc: BaseException) -> RateLimitError:
    """Normalize an arbitrary exception into a RateLimitError."""
    if isinstance(exc, RateLimitError):
        return exc
    return RateLimitError(str(exc))


def raise_if_rate_limited(exc: BaseException) -> None:
    """Re-raise rate-limit failures as RateLimitError."""
    if is_rate_limit_error(exc):
        raise as_rate_limit_error(exc) from exc


def build_sse_error_payload(exc: BaseException) -> dict:
    """Convert backend exceptions into SSE error payloads."""
    if is_rate_limit_error(exc):
        return as_rate_limit_error(exc).to_payload()
    return {"message": str(exc)}
