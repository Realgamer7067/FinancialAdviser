"""Typed adapter errors (plan section 3). Adapters raise these; they never
turn a failure into an empty portfolio. Messages must never contain tokens,
PINs, TOTPs, raw client codes or response bodies."""

AUTH_EXPIRED = "AUTH_EXPIRED"
RATE_LIMITED = "RATE_LIMITED"
PARTIAL_DATA = "PARTIAL_DATA"
UNAVAILABLE = "UNAVAILABLE"
IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
BAD_RESPONSE = "BAD_RESPONSE"  # unknown envelope / schema drift -- rejected, never guessed


class AngelError(Exception):
    code = UNAVAILABLE

    def __init__(self, message: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class AuthExpired(AngelError):
    code = AUTH_EXPIRED


class RateLimited(AngelError):
    code = RATE_LIMITED


class Unavailable(AngelError):
    code = UNAVAILABLE


class BadResponse(AngelError):
    code = BAD_RESPONSE


class IdentityConflict(AngelError):
    code = IDENTITY_CONFLICT
