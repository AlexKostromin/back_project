from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.error_handlers import register_exception_handlers
from app.core.exceptions import AppError, NotFoundError


class _TestError(AppError):
    code = "test_error"
    status_code = 418
    detail = "I am a teapot"


def _build_app() -> FastAPI:
    """Build a throwaway FastAPI app with the exception handlers wired and a
    handful of routes that raise different exception types."""

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise-app-error")
    async def _app_error() -> None:
        raise _TestError()

    @app.get("/raise-not-found")
    async def _not_found() -> None:
        raise NotFoundError()

    @app.get("/raise-unhandled")
    async def _unhandled() -> None:
        raise RuntimeError("boom")

    @app.get("/raise-with-field")
    async def _with_field() -> None:
        raise _TestError(field="email")

    return app


@pytest.mark.asyncio
async def test_app_error_is_rendered_as_structured_json() -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-app-error")

    assert response.status_code == 418
    assert response.json() == {
        "detail": "I am a teapot",
        "code": "test_error",
        "field": None,
    }


@pytest.mark.asyncio
async def test_not_found_maps_to_404() -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-not-found")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Resource not found",
        "code": "not_found",
        "field": None,
    }


@pytest.mark.asyncio
async def test_unhandled_exception_returns_generic_500() -> None:
    app = _build_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-unhandled")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "code": "internal_error",
        "field": None,
    }


@pytest.mark.asyncio
async def test_app_error_passes_field_through() -> None:
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-with-field")

    assert response.status_code == 418
    assert response.json()["field"] == "email"
