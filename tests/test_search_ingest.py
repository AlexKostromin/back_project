from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import session as db_session
from app.db.models import CourtDecision
from app.main import app
from tests.conftest import TEST_ES_INDEX


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
async def test_ingest_creates_decision_in_pg_and_es(
    clean_search_tables, clean_es_index
):
    es = clean_es_index

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/ingest/decision",
            json=_raw_payload(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    decision_id = body["decision_id"]
    assert decision_id is not None
    assert len(body["text_hash"]) == 64

    # Postgres: es_indexed flipped to True after successful ES write.
    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(CourtDecision).where(CourtDecision.id == decision_id)
            )
        ).scalar_one()
        assert row.es_indexed is True

    # Elasticsearch: document lands at the same id with searchable fields.
    doc = await es.get(index=TEST_ES_INDEX, id=str(decision_id))
    assert doc["_source"]["case_number"] == "А40-12345/2025"
    assert doc["_source"]["court_type"] == "arbitrazh"
    assert doc["_source"]["full_text"] == "текст решения суда"
    assert doc["_source"]["participants"][0]["name"] == "ООО Ромашка"


@pytest.mark.asyncio
async def test_ingest_is_idempotent_on_duplicate_full_text(
    clean_search_tables, clean_es_index
):
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


@pytest.mark.asyncio
async def test_ingest_survives_es_failure(
    clean_search_tables, clean_es_index, monkeypatch
):
    """If ES refuses the write (e.g. index temporarily offline), the
    ingest still commits to Postgres and returns CREATED — es_indexed
    stays False so a reindex task can pick it up later."""

    from app.modules.search.services import processor as processor_module

    async def _boom(self, decision) -> None:
        raise RuntimeError("simulated ES outage")

    monkeypatch.setattr(processor_module.DecisionProcessor, "_index_in_es", _boom)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/ingest/decision",
            json=_raw_payload(text="es down but pg ok"),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "created"

    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(CourtDecision).where(
                    CourtDecision.id == response.json()["decision_id"]
                )
            )
        ).scalar_one()
        assert row.es_indexed is False
