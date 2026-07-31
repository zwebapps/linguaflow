"""Typed application errors + the single JSON error envelope from API_CONTRACT.md §0.

Every failure the client can see goes through here, so the frontend only ever has
to read `error.message`.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger(__name__)


class AppError(Exception):
    """Base class for every error we deliberately surface to a client."""

    code = "internal_error"
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "Something went wrong on our side."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.details = details or []
        self.headers = headers or {}


class ValidationError(AppError):
    code = "validation_error"
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    message = "The request was invalid."


class Unauthorized(AppError):
    code = "unauthorized"
    status_code = status.HTTP_401_UNAUTHORIZED
    message = "Sign in to continue."


class Forbidden(AppError):
    code = "forbidden"
    status_code = status.HTTP_403_FORBIDDEN
    message = "You don't have access to this."


class NotFound(AppError):
    code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND
    message = "Not found."


class RateLimited(AppError):
    code = "rate_limited"
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Too many requests. Please slow down."

    def __init__(self, retry_after: int = 30, **kw: Any) -> None:
        super().__init__(
            f"Too many requests. Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
            **kw,
        )


class QuotaExceeded(AppError):
    code = "forbidden"
    status_code = status.HTTP_403_FORBIDDEN
    message = "You've used your monthly AI allowance."


class UpstreamError(AppError):
    """A third party (OpenRouter, Qdrant, a fetched URL) failed."""

    code = "upstream_error"
    status_code = status.HTTP_502_BAD_GATEWAY
    message = "An upstream service failed. Please retry."


class AllModelsFailed(AppError):
    """Every model in the route's fallback chain failed — see ai/router.py."""

    code = "all_models_failed"
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "All AI models are unavailable right now. Please retry shortly."


class ToolExecutionError(AppError):
    code = "upstream_error"
    status_code = status.HTTP_502_BAD_GATEWAY
    message = "A tool failed while answering your question."


def _envelope(
    code: str,
    message: str,
    request_id: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": request_id,
        }
    }


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        # Client-caused (4xx) is expected traffic; 5xx is ours and worth an error log.
        logger = log.warning if exc.status_code < 500 else log.error
        logger(
            "app_error",
            code=exc.code,
            status=exc.status_code,
            message=exc.message,
            path=request.url.path,
            request_id=_request_id(request),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, _request_id(request), exc.details),
            headers=exc.headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _pydantic_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(p) for p in err["loc"][1:]) or "body",
                "issue": err["msg"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_envelope(
                "validation_error",
                "Some fields need fixing.",
                _request_id(request),
                details,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            429: "rate_limited",
        }.get(exc.status_code, "internal_error")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, str(exc.detail), _request_id(request)),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals to the client; the request_id ties it to the log line.
        log.exception(
            "unhandled_exception",
            path=request.url.path,
            request_id=_request_id(request),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                "internal_error",
                "Something went wrong on our side.",
                _request_id(request),
            ),
        )
