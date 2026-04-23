from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError

log = structlog.get_logger(__name__)


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    log.warning(
        "app_error",
        code=exc.code,
        status_code=exc.status_code,
        detail=exc.detail,
        field=exc.field,
        path=request.url.path,
        method=request.method,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code, "field": exc.field},
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception(
        "unhandled_error",
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "code": "internal_error",
            "field": None,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach domain and fallback exception handlers to the FastAPI app.

    ``AppError`` and its subclasses are rendered as structured JSON with the
    status code declared on the exception. Any other ``Exception`` is logged
    with a full stack trace and returned to the client as a generic 500,
    without leaking internal details.
    """

    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
