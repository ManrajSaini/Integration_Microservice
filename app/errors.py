class ProviderError(Exception):
    """Base class for all adapter-raised errors."""


class AuthenticationError(ProviderError):
    """Invalid/expired credentials that a retry won't fix."""


class TokenRefreshError(ProviderError):
    """Refresh token is invalid, expired, or revoked (invalid_grant)."""


class RateLimitedError(ProviderError):
    """429 — caller should back off and retry."""


class TransientProviderError(ProviderError):
    """5xx or network-level failure — caller should back off and retry."""


class ValidationError(ProviderError):
    """400 — malformed request, not retryable."""


class NotFoundError(ProviderError):
    """404 — not retryable."""


class ConflictError(ProviderError):
    """409 — duplicate unique property."""
