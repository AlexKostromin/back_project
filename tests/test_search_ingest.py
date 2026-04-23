from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _raw_payload(case_number: str = "А40-12345/2025", text: str = "текст решения суда") -> dict:
    return {
        "source_id": "arbitr-1",
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
async def test_ingest_creates_decision(clean_search_tables):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/ingest/decision",
            json=_raw_payload(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["decision_id"] is not None
    assert len(body["text_hash"]) == 64


@pytest.mark.asyncio
async def test_ingest_is_idempotent_on_duplicate_full_text(clean_search_tables):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/v1/search/ingest/decision",
            json=_raw_payload(text="одинаковый текст решения"),
        )
        second = await client.post(
            "/api/v1/search/ingest/decision",
            json=_raw_payload(case_number="А40-99999/2025", text="одинаковый текст решения"),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "created"
    assert second.json()["status"] == "duplicate"
    assert first.json()["decision_id"] == second.json()["decision_id"]
    assert first.json()["text_hash"] == second.json()["text_hash"]


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_payload():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = _raw_payload()
        payload["court_type"] = "unknown_court"
        response = await client.post("/api/v1/search/ingest/decision", json=payload)

    assert response.status_code == 422
