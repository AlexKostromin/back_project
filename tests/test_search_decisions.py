from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.main import app
from app.modules.search.api import decisions as decisions_api
from app.modules.search.schemas.raw_decision import RawDecision


def _raw_payload(case_number: str = "А40-77777/2025", text: str = "текст решения") -> dict[str, Any]:
    return {
        "source_id": "arbitr-read-1",
        "source_name": "arbitr",
        "case_number": case_number,
        "court_name": "Арбитражный суд города Москвы",
        "court_type": "arbitrazh",
        "instance_level": 1,
        "region": "Москва",
        "decision_date": "2025-06-01",
        "publication_date": "2025-06-05",
        "doc_type": "решение",
        "judges": ["Иванов И.И."],
        "result": "satisfied",
        "appeal_status": "none",
        "dispute_type": "civil",
        "category": "Поставка",
        "claim_amount": "100000.00",
        "participants": [
            {"name": "ООО Ромашка", "role": "plaintiff", "inn": "7701234567", "ogrn": None},
            {"name": "ООО Василёк", "role": "defendant", "inn": None, "ogrn": None},
        ],
        "norms": [
            {
                "law_name": "ГК РФ",
                "article": "506",
                "part": None,
                "paragraph": None,
                "raw_ref": "ст. 506 ГК РФ",
            }
        ],
        "full_text": text,
        "sections": {
            "intro": None,
            "descriptive": None,
            "motivational": None,
            "resolutive": "Иск удовлетворить.",
        },
        "source_url": "https://kad.arbitr.ru/Card/xxx",
        "raw_html": None,
        "pdf_url": None,
    }


@pytest.mark.asyncio
async def test_get_decision_happy_path(clean_search_tables, clean_es_index) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ingest = await client.post(
            "/api/v1/search/ingest/decision",
            json=_raw_payload(),
        )
        assert ingest.status_code == 200
        decision_id = ingest.json()["decision_id"]

        response = await client.get(f"/api/v1/search/decisions/{decision_id}")

    assert response.status_code == 200
    body = response.json()

    assert body["id"] == decision_id
    assert body["source_id"] == "arbitr-read-1"
    assert body["source_name"] == "arbitr"
    assert body["case_number"] == "А40-77777/2025"
    assert body["court_name"] == "Арбитражный суд города Москвы"
    assert body["court_type"] == "arbitrazh"
    assert body["instance_level"] == 1
    assert body["region"] == "Москва"
    assert body["decision_date"] == "2025-06-01"
    assert body["publication_date"] == "2025-06-05"
    assert body["doc_type"] == "решение"
    assert body["judges"] == ["Иванов И.И."]
    assert body["result"] == "satisfied"
    assert body["appeal_status"] == "none"
    assert body["dispute_type"] == "civil"
    assert body["category"] == "Поставка"
    assert body["claim_amount"] == "100000.00"
    assert body["full_text"] == "текст решения"
    assert body["sections"] == {
        "intro": None,
        "descriptive": None,
        "motivational": None,
        "resolutive": "Иск удовлетворить.",
    }
    assert len(body["text_hash"]) == 64
    assert body["source_url"].startswith("https://kad.arbitr.ru/Card/")
    assert body["es_indexed"] is True
    assert body["qdrant_indexed"] is False
    assert "created_at" in body
    assert "updated_at" in body

    assert isinstance(body["participants"], list)
    assert len(body["participants"]) == 2
    plaintiff = next(p for p in body["participants"] if p["role"] == "plaintiff")
    defendant = next(p for p in body["participants"] if p["role"] == "defendant")
    assert plaintiff["name"] == "ООО Ромашка"
    assert plaintiff["inn"] == "7701234567"
    assert plaintiff["decision_id"] == decision_id
    assert defendant["name"] == "ООО Василёк"
    assert defendant["inn"] is None
    assert defendant["decision_id"] == decision_id

    assert isinstance(body["norms"], list)
    assert len(body["norms"]) == 1
    norm = body["norms"][0]
    assert norm["law_name"] == "ГК РФ"
    assert norm["article"] == "506"
    assert norm["raw_ref"] == "ст. 506 ГК РФ"
    assert norm["decision_id"] == decision_id


@pytest.mark.asyncio
async def test_get_decision_not_found(clean_search_tables) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/search/decisions/999999999")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Decision not found",
        "code": "decision_not_found",
        "field": None,
    }


@pytest.mark.asyncio
async def test_get_decision_invalid_id_type_returns_422() -> None:
    """Fixes behavior: path param is typed ``int`` — a non-numeric id yields
    422 from FastAPI's path validation layer, not 404."""

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/search/decisions/abc")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_decision_unhandled_error_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any exception not derived from AppError must be rendered by the global
    handler as a generic 500 without leaking internals."""

    class _BoomService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def get(self, decision_id: int) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(decisions_api, "DecisionService", _BoomService)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/search/decisions/1")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "code": "internal_error",
        "field": None,
    }


def test_raw_decision_rejects_full_text_over_limit() -> None:
    """``full_text`` is capped at 10_000_000 characters by Pydantic. Build the
    oversize string lazily and drop it before the assertion so we don't hold
    tens of MB of RAM longer than necessary."""

    payload = _raw_payload()
    payload["full_text"] = "a" * (10_000_000 + 1)

    with pytest.raises(ValidationError) as exc_info:
        RawDecision.model_validate(payload)

    del payload
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("full_text",) for err in errors)


def test_raw_decision_rejects_raw_html_over_limit() -> None:
    """``raw_html`` is capped at 20_000_000 characters by Pydantic."""

    payload = _raw_payload()
    payload["raw_html"] = "b" * (20_000_000 + 1)

    with pytest.raises(ValidationError) as exc_info:
        RawDecision.model_validate(payload)

    del payload
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("raw_html",) for err in errors)
