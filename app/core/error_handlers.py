from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError
from app.llm.exceptions import LLMRateLimitError

log = structlog.get_logger(__name__)

# Сколько секунд клиенту имеет смысл подождать перед повтором при
# 503 от LLM-провайдера. На demo-тарифе GigaChat это скорее
# вежливый намёк, чем точное время восстановления — лимит сбрасывается
# по месячному окну, но 60s даёт UI приличный default для бэкоффа.
_LLM_RETRY_AFTER_SECONDS = 60


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
    headers: dict[str, str] | None = None
    if isinstance(exc, LLMRateLimitError):
        # 503 без Retry-After — это пощёчина клиенту: непонятно, ждать
        # секунду или час. Заголовок даёт фронту явный сигнал бэкоффа.
        headers = {"Retry-After": str(_LLM_RETRY_AFTER_SECONDS)}
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code, "field": exc.field},
        headers=headers,
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
