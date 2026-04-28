"""Тесты слайса B (NLQ-парсер).

Покрывает:
* ``GigaChatAdapter.parse_search_query`` — happy path с разными
  фильтрами, fallback на не-JSON / ValidationError, retry на 401,
  отказ на 429/timeout, контрактные сбои → ``LLMResponseError``,
  безопасность логов (без сырого текста и без секретов).
* Endpoint ``POST /api/v1/search/decisions/nlq`` — happy path
  с реальным ES, валидация cap'а на ``text``, маппинг
  LLM-исключений в HTTP-коды.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
import structlog
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response

from app.core.config import Settings
from app.llm.adapters.gigachat import GigaChatAdapter
from app.llm.dependencies import get_llm_gateway
from app.llm.exceptions import (
    LLMAuthError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.gateway import LLMGateway
from app.main import app
from app.modules.search.schemas.search import SearchDecisionsRequest
from app.modules.search.schemas.summary import DecisionSummary


# ---------------------------------------------------------------------------
# Helpers (повторяют стиль tests/test_llm_summary.py — намеренно
# не импортируем оттуда, чтобы тестовый модуль был самодостаточным).
# ---------------------------------------------------------------------------


def _test_settings() -> Settings:
    return Settings(
        gigachat_client_id="test-client-id",
        gigachat_client_secret="test-client-secret",
        gigachat_scope="GIGACHAT_API_PERS",
        gigachat_model="GigaChat",
        gigachat_max_input_chars=24000,
    )


def _oauth_response(*, expires_in_s: int = 1800, token: str = "tok-abc") -> Response:
    expires_at_ms = int(
        (datetime.now(timezone.utc) + timedelta(seconds=expires_in_s)).timestamp() * 1000
    )
    return Response(200, json={"access_token": token, "expires_at": expires_at_ms})


def _nlq_chat_response(
    *,
    content: str | dict[str, Any] | None = None,
    total_tokens: int = 200,
) -> Response:
    """chat/completions ответ с заданным content (str или JSON-сериализуемый dict)."""

    if isinstance(content, dict):
        content_str = json.dumps(content, ensure_ascii=False)
    elif isinstance(content, str):
        content_str = content
    else:
        content_str = json.dumps(
            {"query": "налог", "sort_by": "relevance"}, ensure_ascii=False
        )
    return Response(
        200,
        json={
            "choices": [{"message": {"content": content_str}}],
            "usage": {"total_tokens": total_tokens},
        },
    )


class _Counter:
    def __init__(self) -> None:
        self.oauth = 0
        self.chat = 0


def _build_handler(
    counter: _Counter,
    *,
    chat_responses: list[Response] | None = None,
    chat_exceptions: list[Exception | None] | None = None,
    oauth_responses: list[Response] | None = None,
):
    chat_responses = chat_responses or [_nlq_chat_response()]
    chat_exceptions = chat_exceptions or []
    oauth_responses = oauth_responses or [_oauth_response()]

    def handler(request: Request) -> Response:
        if "/oauth" in request.url.path:
            idx = min(counter.oauth, len(oauth_responses) - 1)
            counter.oauth += 1
            return oauth_responses[idx]
        if "/chat/completions" in request.url.path:
            idx = counter.chat
            counter.chat += 1
            if idx < len(chat_exceptions) and chat_exceptions[idx] is not None:
                raise chat_exceptions[idx]
            resp_idx = min(idx, len(chat_responses) - 1)
            return chat_responses[resp_idx]
        return Response(404)

    return handler


def _build_adapter(handler) -> GigaChatAdapter:
    transport = MockTransport(handler)
    client = AsyncClient(transport=transport)
    return GigaChatAdapter(_test_settings(), http_client=client)


# ---------------------------------------------------------------------------
# A. Unit-тесты GigaChatAdapter.parse_search_query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_happy_path_full_filters() -> None:
    counter = _Counter()
    full = {
        "query": "налог",
        "court_type": "arbitrazh",
        "region": "Москва",
        "dispute_type": "admin",
        "result": "satisfied",
        "date_from": "2025-01-01",
        "date_to": "2025-12-31",
        "sort_by": "relevance",
    }
    adapter = _build_adapter(
        _build_handler(
            counter,
            chat_responses=[_nlq_chat_response(content=full, total_tokens=275)],
        )
    )

    parsed, tokens = await adapter.parse_search_query(
        "налоговые споры в Москве за 2025 где истец выиграл"
    )

    assert isinstance(parsed, SearchDecisionsRequest)
    assert parsed.query == "налог"
    assert parsed.court_type.value == "arbitrazh"
    assert parsed.region == "Москва"
    assert parsed.dispute_type.value == "admin"
    assert parsed.result.value == "satisfied"
    assert str(parsed.date_from) == "2025-01-01"
    assert str(parsed.date_to) == "2025-12-31"
    assert parsed.sort_by.value == "relevance"
    assert tokens == 275


@pytest.mark.asyncio
async def test_parse_minimal_filters() -> None:
    counter = _Counter()
    minimal = {"query": "поставка", "sort_by": "relevance"}
    adapter = _build_adapter(
        _build_handler(
            counter,
            chat_responses=[_nlq_chat_response(content=minimal, total_tokens=120)],
        )
    )

    parsed, tokens = await adapter.parse_search_query("поставка")

    assert parsed.query == "поставка"
    assert parsed.court_type is None
    assert parsed.region is None
    assert parsed.dispute_type is None
    assert parsed.sort_by.value == "relevance"
    assert tokens == 120


@pytest.mark.asyncio
async def test_parse_falls_back_on_invalid_json() -> None:
    counter = _Counter()
    adapter = _build_adapter(
        _build_handler(
            counter,
            chat_responses=[
                _nlq_chat_response(content="это не json {", total_tokens=60)
            ],
        )
    )

    with structlog.testing.capture_logs() as logs:
        parsed, tokens = await adapter.parse_search_query("какой-то непонятный текст")

    assert parsed.query == "какой-то непонятный текст"
    assert parsed.court_type is None
    assert tokens == 60  # tokens_used отдаём как есть, без потерь
    failed = [e for e in logs if e.get("event") == "nlq.parse_failed"]
    assert len(failed) == 1
    assert failed[0]["reason"] == "non_json"


@pytest.mark.asyncio
async def test_parse_falls_back_on_validation_error_on_bad_enum() -> None:
    counter = _Counter()
    bad = {"query": "x", "court_type": "военный", "sort_by": "date_desc"}
    adapter = _build_adapter(
        _build_handler(
            counter,
            chat_responses=[_nlq_chat_response(content=bad, total_tokens=80)],
        )
    )

    with structlog.testing.capture_logs() as logs:
        parsed, tokens = await adapter.parse_search_query("военные суды")

    assert parsed.query == "военные суды"  # fallback использует исходный текст
    assert parsed.court_type is None
    assert tokens == 80
    failed = [e for e in logs if e.get("event") == "nlq.parse_failed"]
    assert len(failed) == 1
    assert failed[0]["reason"] == "validation"


@pytest.mark.asyncio
async def test_parse_falls_back_on_non_object_json() -> None:
    counter = _Counter()
    # JSON-валидный, но не объект — массив. Тоже должен fallback'ить.
    adapter = _build_adapter(
        _build_handler(
            counter,
            chat_responses=[_nlq_chat_response(content="[1, 2, 3]", total_tokens=10)],
        )
    )

    with structlog.testing.capture_logs() as logs:
        parsed, tokens = await adapter.parse_search_query("xxx")

    assert parsed.query == "xxx"
    assert tokens == 10
    failed = [e for e in logs if e.get("event") == "nlq.parse_failed"]
    assert len(failed) == 1
    assert failed[0]["reason"] == "non_object"


@pytest.mark.asyncio
async def test_parse_raises_response_error_on_broken_envelope() -> None:
    counter = _Counter()
    # choices есть, но usage отсутствует — сломанный OpenAI-конверт.
    broken = Response(200, json={"choices": [{"message": {"content": "{}"}}]})
    adapter = _build_adapter(
        _build_handler(counter, chat_responses=[broken])
    )

    with pytest.raises(LLMResponseError):
        await adapter.parse_search_query("любой текст")


@pytest.mark.asyncio
async def test_parse_retries_once_on_401() -> None:
    counter = _Counter()
    handler = _build_handler(
        counter,
        chat_responses=[Response(401), _nlq_chat_response()],
        oauth_responses=[
            _oauth_response(token="t1"),
            _oauth_response(token="t2"),
        ],
    )
    adapter = _build_adapter(handler)

    parsed, tokens = await adapter.parse_search_query("текст")

    assert isinstance(parsed, SearchDecisionsRequest)
    assert counter.chat == 2
    assert counter.oauth == 2  # initial + force-refresh


@pytest.mark.asyncio
async def test_parse_raises_rate_limit_on_429_without_retry() -> None:
    counter = _Counter()
    adapter = _build_adapter(
        _build_handler(counter, chat_responses=[Response(429)])
    )

    with pytest.raises(LLMRateLimitError):
        await adapter.parse_search_query("текст")
    assert counter.chat == 1  # без retry


@pytest.mark.asyncio
async def test_parse_raises_timeout() -> None:
    counter = _Counter()
    adapter = _build_adapter(
        _build_handler(
            counter,
            chat_exceptions=[httpx.TimeoutException("read timeout")],
        )
    )

    with pytest.raises(LLMTimeoutError):
        await adapter.parse_search_query("текст")


@pytest.mark.asyncio
async def test_parse_logs_filter_names_not_values_or_text() -> None:
    counter = _Counter()
    sensitive = {
        "query": "Иванов Иван Иванович ИНН 770123456789",
        "court_type": "arbitrazh",
        "region": "Москва",
        "sort_by": "relevance",
    }
    adapter = _build_adapter(
        _build_handler(
            counter,
            chat_responses=[_nlq_chat_response(content=sensitive, total_tokens=150)],
        )
    )

    with structlog.testing.capture_logs() as logs:
        await adapter.parse_search_query(
            "найди дела где истец Иванов И.И. ИНН 770123456789"
        )

    parsed_events = [e for e in logs if e.get("event") == "nlq.parsed"]
    assert len(parsed_events) == 1
    event = parsed_events[0]

    # В parsed_filters только имена непустых полей.
    assert "court_type" in event["parsed_filters"]
    assert "region" in event["parsed_filters"]
    assert "query" in event["parsed_filters"]

    # Сериализуем все логи и проверяем, что ни сырой текст,
    # ни значения чувствительных полей не попали никуда.
    serialized = json.dumps(logs, ensure_ascii=False, default=str)
    assert "Иванов" not in serialized
    assert "770123456789" not in serialized
    assert "Москва" not in serialized  # значение region не должно светиться


@pytest.mark.asyncio
async def test_parse_does_not_log_client_secret_on_oauth_failure() -> None:
    counter = _Counter()
    adapter = _build_adapter(
        _build_handler(counter, oauth_responses=[Response(401)])
    )

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(LLMAuthError):
            await adapter.parse_search_query("текст")

    serialized = json.dumps(logs, ensure_ascii=False)
    assert "test-client-secret" not in serialized
    assert "test-client-id" not in serialized


@pytest.mark.asyncio
async def test_summarize_still_works_after_helper_extraction() -> None:
    """Регрессия: ``summarize()`` не должен сломаться из-за выноса
    транспортного пути в общий ``_chat_with_token_refresh``-helper."""

    counter = _Counter()
    summary_payload = {
        "summary": "Тест.",
        "key_norms": ["ГК РФ ст. 1"],
        "parties_brief": "А vs Б",
        "outcome": "иск удовлетворён",
    }
    chat = Response(
        200,
        json={
            "choices": [
                {"message": {"content": json.dumps(summary_payload, ensure_ascii=False)}}
            ],
            "usage": {"total_tokens": 50},
        },
    )
    adapter = _build_adapter(_build_handler(counter, chat_responses=[chat]))

    result = await adapter.summarize("Текст решения.")

    assert isinstance(result, DecisionSummary)
    assert result.tokens_used == 50


# ---------------------------------------------------------------------------
# B. Endpoint smoke (FastAPI + замоканый gateway, реальные PG/ES)
# ---------------------------------------------------------------------------


def _ingest_payload(
    *,
    case_number: str = "А40-NLQ-1/2025",
    text: str = "поставка товаров надлежащего качества",
    region: str = "Москва",
    dispute_type: str = "civil",
    result: str = "satisfied",
) -> dict[str, Any]:
    return {
        "source_id": f"src-nlq-{case_number}",
        "source_name": "arbitr",
        "case_number": case_number,
        "court_name": "Арбитражный суд города Москвы",
        "court_type": "arbitrazh",
        "instance_level": 1,
        "region": region,
        "decision_date": "2025-06-01",
        "publication_date": "2025-06-05",
        "doc_type": "решение",
        "judges": ["Иванов И.И."],
        "result": result,
        "appeal_status": "none",
        "dispute_type": dispute_type,
        "category": "Поставка",
        "claim_amount": "100000.00",
        "participants": [
            {"name": "ООО А", "role": "plaintiff", "inn": None, "ogrn": None},
            {"name": "ООО Б", "role": "defendant", "inn": None, "ogrn": None},
        ],
        "norms": [],
        "full_text": text,
        "sections": {
            "intro": None,
            "descriptive": None,
            "motivational": None,
            "resolutive": "Иск удовлетворить.",
        },
        "source_url": "https://kad.arbitr.ru/Card/nlq",
        "raw_html": None,
        "pdf_url": None,
    }


class _FakeNLQGateway(LLMGateway):
    """Подменяемый gateway для endpoint-тестов NLQ."""

    def __init__(
        self,
        *,
        parse_result: tuple[SearchDecisionsRequest, int] | None = None,
        parse_raises: Exception | None = None,
    ) -> None:
        self._parse_result = parse_result
        self._parse_raises = parse_raises
        self.parse_calls = 0

    async def summarize(self, text: str) -> DecisionSummary:  # pragma: no cover
        raise NotImplementedError

    async def parse_search_query(
        self, text: str
    ) -> tuple[SearchDecisionsRequest, int]:
        self.parse_calls += 1
        if self._parse_raises is not None:
            raise self._parse_raises
        assert self._parse_result is not None
        return self._parse_result


def _install_gateway(gw: LLMGateway) -> None:
    app.dependency_overrides[get_llm_gateway] = lambda: gw


def _uninstall_gateway() -> None:
    app.dependency_overrides.pop(get_llm_gateway, None)


@pytest.fixture
def cleanup_gateway():
    yield
    _uninstall_gateway()


@pytest.mark.asyncio
async def test_endpoint_happy_path(
    clean_search_tables, clean_es_index, cleanup_gateway
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ingest = await client.post(
            "/api/v1/search/ingest/decision", json=_ingest_payload()
        )
        assert ingest.status_code == 200

        # Refresh ES, чтобы документ был виден поиску немедленно.
        await clean_es_index.indices.refresh(index="test_court_decisions")

        parsed = SearchDecisionsRequest(
            region="Москва", dispute_type="civil", sort_by="date_desc"
        )
        _install_gateway(_FakeNLQGateway(parse_result=(parsed, 200)))

        response = await client.post(
            "/api/v1/search/decisions/nlq",
            json={"text": "поставка товаров в Москве"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["parsed_query"]["region"] == "Москва"
    assert body["parsed_query"]["dispute_type"] == "civil"
    assert body["tokens_used"] == 200
    # Пригодность результатов: общая структура SearchDecisionsResponse.
    assert "total" in body["results"]
    assert "page" in body["results"]
    assert "page_size" in body["results"]
    assert "items" in body["results"]
    assert body["results"]["total"] >= 1


@pytest.mark.asyncio
async def test_endpoint_returns_full_results_envelope_even_for_empty(
    clean_search_tables, clean_es_index, cleanup_gateway
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Никаких документов не сидим — выдача пустая, но envelope должен быть.
        parsed = SearchDecisionsRequest(query="несуществующее")
        _install_gateway(_FakeNLQGateway(parse_result=(parsed, 50)))

        response = await client.post(
            "/api/v1/search/decisions/nlq", json={"text": "что-то"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["results"]["total"] == 0
    assert body["results"]["items"] == []
    assert body["tokens_used"] == 50


@pytest.mark.asyncio
async def test_endpoint_rejects_too_long_text(cleanup_gateway) -> None:
    # Cap = 512 в pydantic-схеме.
    long_text = "а" * 600
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions/nlq", json={"text": long_text}
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_rejects_empty_text(cleanup_gateway) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions/nlq", json={"text": ""}
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_rejects_extra_fields(cleanup_gateway) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions/nlq",
            json={"text": "ok", "extra": "should fail"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_503_with_retry_after_on_rate_limit(
    clean_search_tables, clean_es_index, cleanup_gateway
) -> None:
    _install_gateway(_FakeNLQGateway(parse_raises=LLMRateLimitError()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions/nlq", json={"text": "что угодно"}
        )

    assert response.status_code == 503
    assert response.headers.get("retry-after") == "60"
    assert response.json()["code"] == "llm_rate_limited"


@pytest.mark.asyncio
async def test_endpoint_504_on_timeout(
    clean_search_tables, clean_es_index, cleanup_gateway
) -> None:
    _install_gateway(_FakeNLQGateway(parse_raises=LLMTimeoutError()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions/nlq", json={"text": "что-то"}
        )

    assert response.status_code == 504


@pytest.mark.asyncio
async def test_endpoint_502_on_response_error(
    clean_search_tables, clean_es_index, cleanup_gateway
) -> None:
    _install_gateway(_FakeNLQGateway(parse_raises=LLMResponseError()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/search/decisions/nlq", json={"text": "что-то"}
        )

    assert response.status_code == 502
