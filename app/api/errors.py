import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    RateLimitedError,
    TokenRefreshError,
    TransientProviderError,
    ValidationError,
)

_STATUS_BY_ERROR: dict[type[Exception], tuple[int, str]] = {
    AuthenticationError: (401, "AUTHENTICATION_ERROR"),
    TokenRefreshError: (401, "TOKEN_REFRESH_FAILED"),
    ValidationError: (400, "VALIDATION_ERROR"),
    NotFoundError: (404, "NOT_FOUND"),
    ConflictError: (409, "CONFLICT"),
    RateLimitedError: (429, "RATE_LIMITED"),
    TransientProviderError: (502, "UPSTREAM_UNAVAILABLE"),
}


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "correlation_id": str(uuid.uuid4()),
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    for exc_type, (status_code, code) in _STATUS_BY_ERROR.items():

        def handler(request: Request, exc: Exception, status_code=status_code, code=code):
            return _error_response(status_code, code, str(exc))

        app.add_exception_handler(exc_type, handler)
