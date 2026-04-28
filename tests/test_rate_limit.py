"""Тесты per-IP rate-limit'а на LLM-эндпоинтах.

Проверяем:
* После 10-го запроса в минуту с одного IP 11-й получает 429 с
  ``Retry-After: 60`` и единым JSON-форматом ``{detail, code, field}``.
* Поиск без LLM (``POST /decisions``) — НЕ под лимитом, его никакая
  пользовательская активность не должна заблокировать.
* JSON-формат 429 совпадает с остальными ``AppError``-ответами.

Лимит дефолтный 10/minute (``Settings.llm_rate_limit_per_minute``).
``conftest._reset_engine_cache`` сбрасывает счётчики между тестами, так
что внутри одного теста мы видим чистый счётчик с нуля.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import session as db_session
from app.db.models import CourtDecision, DecisionNorm, DecisionParticipant
from app.llm.dependencies import get_llm_gateway
from app.llm.gateway import LLMGateway
from app.main import app
from app.modules.search.schemas.search import SearchDecisionsRequest
from app.modules.search.schemas.summary import DecisionSummary


_FAKE_SUMMARY = DecisionSummary(
    summary="rate-limit smoke",
    key_norms=[],
    parties_brief="x",
    outcome="y",
    tokens_used=1,
)


class _FakeGateway(LLMGateway):
    """Мгновенный gateway — нам в этих тестах важна частота, не контент."""

    async def summarize(self, text: str) -> DecisionSummary:
        return _FAKE_SUMMARY

    async def parse_search_query(
        self, text: str
    ) -> tuple[SearchDecisionsRequest, int]:
        return SearchDecisionsRequest(query=text), 1


@pytest.fixture
def fake_gateway():
    app.dependency_overrides[get_llm_gateway] = lambda: _FakeGateway()
    yield
    app.dependency_overrides.pop(get_llm_gateway, None)


def _make_decision() -> CourtDecision:
    now = datetime.now(timezone.utc)
    return CourtDecision(
        source_id="rl-1",
        source_name="arbitr",
        case_number="А40-RL/2025",
        court_name="Арбитражный суд Москвы",
        court_type="arbitrazh",
        instance_level=1,
        region="Москва",
        decision_date=date(2025, 6, 1),
        publication_date=date(2025, 6, 5),
        doc_type="решение",
        judges=["Иванов И.И."],
        result="satisfied",
        appeal_status="none",
        dispute_type="civil",
        category="Поставка",
        claim_amount=Decimal("100000.00"),
        full_text="текст решения для rate-limit smoke",
        sections=None,
        text_hash="rl" + "a" * 62,
        source_url="https://kad.arbitr.ru/Card/rl",
        crawled_at=now,
        parsed_at=now,
        es_indexed=False,
        participants=[
            DecisionParticipant(
                name="ООО А", role="plaintiff", inn=None, ogrn=None
            ),
        ],
        norms=[
            DecisionNorm(
                law_name="ГК РФ",
                article="1",
                part=None,
                paragraph=None,
                raw_ref="ст. 1 ГК РФ",
            ),
        ],
    )


async def _seed_decision() -> int:
    decision = _make_decision()
    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        session.add(decision)
        await session.commit()
        return decision.id


@pytest.mark.asyncio
async def test_summary_rate_limit_blocks_eleventh_request_per_ip(
    clean_search_tables, fake_gateway
) -> None:
    decision_id = await _seed_decision()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Дефолтный лимит — 10/minute. Первые 10 — 200, 11-й — 429.
        for _ in range(10):
            ok = await client.post(
                f"/api/v1/search/decisions/{decision_id}/summary"
            )
            assert ok.status_code == 200

        eleventh = await client.post(
            f"/api/v1/search/decisions/{decision_id}/summary"
        )

    assert eleventh.status_code == 429
    assert eleventh.headers.get("retry-after") == "60"
    body = eleventh.json()
    assert body["code"] == "rate_limit_exceeded"
    assert body["detail"]
    assert body["field"] is None


@pytest.mark.asyncio
async def test_nlq_rate_limit_blocks_eleventh_request_per_ip(
    clean_search_tables, clean_es_index, fake_gateway
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(10):
            ok = await client.post(
                "/api/v1/search/decisions/nlq",
                json={"text": "что-то"},
            )
            assert ok.status_code == 200

        eleventh = await client.post(
            "/api/v1/search/decisions/nlq",
            json={"text": "ещё что-то"},
        )

    assert eleventh.status_code == 429
    assert eleventh.headers.get("retry-after") == "60"
    assert eleventh.json()["code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_search_endpoint_is_not_rate_limited(
    clean_search_tables, clean_es_index
) -> None:
    """Поиск ``POST /decisions`` — без LLM, не должен попадать под лимит.

    Юзер может пагинировать, корректировать фильтры, перезагружать
    страницу — это всё выливается в десятки запросов в минуту с одного IP.
    """

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        statuses: list[int] = []
        for _ in range(15):
            response = await client.post(
                "/api/v1/search/decisions", json={}
            )
            statuses.append(response.status_code)

    assert all(s == 200 for s in statuses), f"Не все 200: {statuses}"


@pytest.mark.asyncio
async def test_429_response_includes_retry_after_header(
    clean_search_tables, clean_es_index, fake_gateway
) -> None:
    """Smoke: ``Retry-After`` обязателен — без него фронт не знает,
    через сколько повторять, и UX превращается в случайные дёрганья."""

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(10):
            await client.post(
                "/api/v1/search/decisions/nlq", json={"text": "x"}
            )
        blocked = await client.post(
            "/api/v1/search/decisions/nlq", json={"text": "x"}
        )

    assert blocked.status_code == 429
    assert "retry-after" in {k.lower() for k in blocked.headers}
    # 60 секунд — не точное «когда лимит освободится», а вежливый
    # default'ный backoff (см. app/core/rate_limit.py).
    assert blocked.headers["retry-after"] == "60"
