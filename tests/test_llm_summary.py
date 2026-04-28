from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
import pytest_asyncio
import structlog
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response

from app.core.config import Settings
from app.db import session as db_session
from app.db.models.court_decision import CourtDecision
from app.llm.adapters.gigachat import GigaChatAdapter
from app.llm.dependencies import get_llm_gateway
from app.llm.exceptions import (
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.gateway import LLMGateway
from app.main import app
from app.modules.search.schemas.summary import DecisionSummary

# ---------------------------------------------------------------------------
# Общие хелперы
# ---------------------------------------------------------------------------

# URL'ы, по которым GigaChatAdapter ходит. ``Settings`` по дефолту даёт
# боевые продовские адреса; в тестах MockTransport матчит запросы по path,
# не по host, поэтому реальный сетевой вызов не уйдёт.
_AUTH_URL_PATH = "/api/v2/oauth"
_CHAT_URL_PATH = "/chat/completions"

_DEFAULT_LLM_CONTENT = {
    "summary": "Истец взыскивал долг по поставке, суд иск удовлетворил.",
    "key_norms": ["ГК РФ ст. 506", "ГК РФ ст. 309"],
    "parties_brief": "ООО Ромашка vs ООО Василёк",
    "outcome": "Иск удовлетворить полностью.",
}


def _test_settings(**overrides: Any) -> Settings:
    """Сборка ``Settings`` без чтения реального .env.

    GigaChat client_id/secret прибиты к фейковым значениям, чтобы тест
    случайно не подцепил рабочий ключ из .env разработчика и не послал
    запрос в продовый Сбер. ``gigachat_ca_bundle_path`` в адаптер не
    попадёт — мы передаём свой ``http_client`` с MockTransport.
    """

    base = {
        "gigachat_client_id": "test-client-id",
        "gigachat_client_secret": "test-client-secret-DO-NOT-LOG",
        "gigachat_scope": "GIGACHAT_API_PERS",
        "gigachat_model": "GigaChat",
        "gigachat_max_input_chars": 24000,
        "gigachat_request_timeout_s": 30.0,
    }
    base.update(overrides)
    return Settings(**base)


def _oauth_response_body(*, ttl_seconds: int = 1800) -> dict[str, Any]:
    """Сбер отдаёт ``expires_at`` как UNIX-ms — повторяем формат."""

    expires_ms = int(
        (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).timestamp()
        * 1000
    )
    return {"access_token": "test-access-token", "expires_at": expires_ms}


def _chat_response_body(
    content: dict[str, Any] | str | None = None,
    *,
    total_tokens: int = 512,
) -> dict[str, Any]:
    """OpenAI-совместимая обёртка над content для chat/completions."""

    if content is None:
        content = _DEFAULT_LLM_CONTENT
    serialized = content if isinstance(content, str) else json.dumps(content)
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": serialized},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 200,
            "completion_tokens": 312,
            "total_tokens": total_tokens,
        },
    }


class _Counter:
    """Минимальный счётчик вызовов handler'а — чище, чем nonlocal int."""

    def __init__(self) -> None:
        self.oauth = 0
        self.chat = 0


def _build_adapter(
    handler,
    *,
    settings: Settings | None = None,
) -> GigaChatAdapter:
    """Собираем адаптер с MockTransport вместо реального httpx-клиента."""

    settings = settings or _test_settings()
    client = httpx.AsyncClient(transport=MockTransport(handler))
    return GigaChatAdapter(settings, http_client=client)


# ---------------------------------------------------------------------------
# A. Unit-тесты GigaChatAdapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarize_happy_path() -> None:
    """Полный flow: OAuth → chat/completions → парсинг в DecisionSummary.

    Ключевое: ``tokens_used`` берётся из ``usage.total_tokens``, а не из
    тела JSON-content (аудит расхода нельзя доверять самой LLM).
    """

    counter = _Counter()

    def handler(request: Request) -> Response:
        if request.url.path == _AUTH_URL_PATH:
            counter.oauth += 1
            return Response(200, json=_oauth_response_body())
        if request.url.path.endswith(_CHAT_URL_PATH):
            counter.chat += 1
            # Подсовываем "галлюцинированный" tokens_used в content,
            # чтобы убедиться, что адаптер его игнорирует и берёт из usage.
            payload = dict(_DEFAULT_LLM_CONTENT)
            payload["tokens_used"] = 999_999
            return Response(200, json=_chat_response_body(payload, total_tokens=512))
        return Response(404)

    adapter = _build_adapter(handler)
    try:
        result = await adapter.summarize("текст судебного решения")
    finally:
        await adapter._http.aclose()

    assert isinstance(result, DecisionSummary)
    assert result.summary == _DEFAULT_LLM_CONTENT["summary"]
    assert result.key_norms == _DEFAULT_LLM_CONTENT["key_norms"]
    assert result.parties_brief == _DEFAULT_LLM_CONTENT["parties_brief"]
    assert result.outcome == _DEFAULT_LLM_CONTENT["outcome"]
    # Critical: tokens_used из usage, НЕ из подсунутого content.
    assert result.tokens_used == 512
    assert counter.oauth == 1
    assert counter.chat == 1


@pytest.mark.asyncio
async def test_summarize_caches_token() -> None:
    """Два подряд summarize() должны делать ровно один OAuth-запрос."""

    counter = _Counter()

    def handler(request: Request) -> Response:
        if request.url.path == _AUTH_URL_PATH:
            counter.oauth += 1
            return Response(200, json=_oauth_response_body())
        if request.url.path.endswith(_CHAT_URL_PATH):
            counter.chat += 1
            return Response(200, json=_chat_response_body())
        return Response(404)

    adapter = _build_adapter(handler)
    try:
        await adapter.summarize("текст 1")
        await adapter.summarize("текст 2")
    finally:
        await adapter._http.aclose()

    assert counter.oauth == 1, "token must be cached across summarize() calls"
    assert counter.chat == 2


@pytest.mark.asyncio
async def test_summarize_refreshes_token_on_expiry() -> None:
    """Если ``_expires_at`` в прошлом — следующий summarize() рефрешит токен."""

    counter = _Counter()

    def handler(request: Request) -> Response:
        if request.url.path == _AUTH_URL_PATH:
            counter.oauth += 1
            return Response(200, json=_oauth_response_body())
        if request.url.path.endswith(_CHAT_URL_PATH):
            counter.chat += 1
            return Response(200, json=_chat_response_body())
        return Response(404)

    adapter = _build_adapter(handler)
    try:
        await adapter.summarize("текст 1")
        assert counter.oauth == 1

        # Принудительно "состариваем" кэшированный токен.
        adapter._expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)

        await adapter.summarize("текст 2")
    finally:
        await adapter._http.aclose()

    assert counter.oauth == 2, "expired token must trigger fresh OAuth fetch"
    assert counter.chat == 2


@pytest.mark.asyncio
async def test_summarize_retries_once_on_401() -> None:
    """401 от chat → один retry с force-refresh токена → 200 → результат успешный."""

    counter = _Counter()

    def handler(request: Request) -> Response:
        if request.url.path == _AUTH_URL_PATH:
            counter.oauth += 1
            return Response(200, json=_oauth_response_body())
        if request.url.path.endswith(_CHAT_URL_PATH):
            counter.chat += 1
            if counter.chat == 1:
                return Response(401, json={"message": "unauthorized"})
            return Response(200, json=_chat_response_body())
        return Response(404)

    adapter = _build_adapter(handler)
    try:
        result = await adapter.summarize("текст")
    finally:
        await adapter._http.aclose()

    assert isinstance(result, DecisionSummary)
    assert counter.oauth == 2, "force-refresh must hit OAuth a second time"
    assert counter.chat == 2


@pytest.mark.asyncio
async def test_summarize_raises_auth_error_on_double_401() -> None:
    """Повторный 401 после refresh → LLMAuthError, не зацикливание."""

    counter = _Counter()

    def handler(request: Request) -> Response:
        if request.url.path == _AUTH_URL_PATH:
            counter.oauth += 1
            return Response(200, json=_oauth_response_body())
        if request.url.path.endswith(_CHAT_URL_PATH):
            counter.chat += 1
            return Response(401, json={"message": "unauthorized"})
        return Response(404)

    adapter = _build_adapter(handler)
    try:
        with pytest.raises(LLMAuthError):
            await adapter.summarize("текст")
    finally:
        await adapter._http.aclose()

    # Ровно две попытки: исходная + retry. Никаких "ещё одной".
    assert counter.chat == 2
    assert counter.oauth == 2


@pytest.mark.asyncio
async def test_summarize_raises_rate_limit_on_429() -> None:
    """429 → LLMRateLimitError БЕЗ retry: на demo-тарифе retry бесполезен."""

    counter = _Counter()

    def handler(request: Request) -> Response:
        if request.url.path == _AUTH_URL_PATH:
            counter.oauth += 1
            return Response(200, json=_oauth_response_body())
        if request.url.path.endswith(_CHAT_URL_PATH):
            counter.chat += 1
            return Response(429, json={"message": "rate limit exceeded"})
        return Response(404)

    adapter = _build_adapter(handler)
    try:
        with pytest.raises(LLMRateLimitError):
            await adapter.summarize("текст")
    finally:
        await adapter._http.aclose()

    assert counter.chat == 1, "429 must not be retried"


@pytest.mark.asyncio
async def test_summarize_raises_response_error_on_invalid_json() -> None:
    """content="это не json" → LLMResponseError."""

    def handler(request: Request) -> Response:
        if request.url.path == _AUTH_URL_PATH:
            return Response(200, json=_oauth_response_body())
        if request.url.path.endswith(_CHAT_URL_PATH):
            return Response(
                200, json=_chat_response_body(content="это не json {[")
            )
        return Response(404)

    adapter = _build_adapter(handler)
    try:
        with pytest.raises(LLMResponseError):
            await adapter.summarize("текст")
    finally:
        await adapter._http.aclose()


@pytest.mark.asyncio
async def test_summarize_raises_response_error_on_pydantic_validation() -> None:
    """JSON валидный, но не хватает обязательного поля outcome → LLMResponseError."""

    incomplete = {
        "summary": "что-то",
        "key_norms": [],
        "parties_brief": "А vs Б",
        # outcome намеренно отсутствует
    }

    def handler(request: Request) -> Response:
        if request.url.path == _AUTH_URL_PATH:
            return Response(200, json=_oauth_response_body())
        if request.url.path.endswith(_CHAT_URL_PATH):
            return Response(200, json=_chat_response_body(incomplete))
        return Response(404)

    adapter = _build_adapter(handler)
    try:
        with pytest.raises(LLMResponseError):
            await adapter.summarize("текст")
    finally:
        await adapter._http.aclose()


@pytest.mark.asyncio
async def test_summarize_truncates_long_input() -> None:
    """Текст длиннее cap'a → срезаем и логируем warning ``llm.input_truncated``."""

    settings = _test_settings(gigachat_max_input_chars=50)
    captured_user_text: dict[str, str] = {}

    def handler(request: Request) -> Response:
        if request.url.path == _AUTH_URL_PATH:
            return Response(200, json=_oauth_response_body())
        if request.url.path.endswith(_CHAT_URL_PATH):
            body = json.loads(request.content.decode("utf-8"))
            # Last message — user message с обрезанным текстом.
            captured_user_text["content"] = body["messages"][-1]["content"]
            return Response(200, json=_chat_response_body())
        return Response(404)

    adapter = _build_adapter(handler, settings=settings)
    long_text = "А" * 1000  # сильно больше cap=50

    with structlog.testing.capture_logs() as logs:
        try:
            result = await adapter.summarize(long_text)
        finally:
            await adapter._http.aclose()

    assert isinstance(result, DecisionSummary)
    # Adapter передал в payload не больше cap+префикс_промпта, content
    # сборки — "Текст решения:\n\n" + truncated; проверяем именно факт
    # обрезки (50 символов "А"-шек, не 1000).
    assert "А" * 50 in captured_user_text["content"]
    assert "А" * 51 not in captured_user_text["content"]

    truncated_logs = [e for e in logs if e.get("event") == "llm.input_truncated"]
    assert len(truncated_logs) == 1
    assert truncated_logs[0]["original_len"] == 1000
    assert truncated_logs[0]["truncated_to"] == 50


@pytest.mark.asyncio
async def test_oauth_client_secret_not_logged() -> None:
    """Любая ошибка OAuth не должна тащить client_secret в structlog-события.

    Это критично для security: GigaChat client_secret даёт полный доступ
    к биллингу, и выгрузка JSON-логов в ELK не должна его содержать.
    """

    secret = "f22d1f0d-CAN-NOT-APPEAR-IN-LOGS"
    settings = _test_settings(gigachat_client_secret=secret)

    def handler(request: Request) -> Response:
        if request.url.path == _AUTH_URL_PATH:
            return Response(401, json={"message": "invalid client"})
        return Response(404)

    adapter = _build_adapter(handler, settings=settings)

    with structlog.testing.capture_logs() as logs:
        try:
            with pytest.raises(LLMAuthError):
                await adapter.summarize("текст")
        finally:
            await adapter._http.aclose()

    for event in logs:
        # Проверяем все строковые значения в logged event'ах рекурсивно.
        flat = json.dumps(event, default=str, ensure_ascii=False)
        assert secret not in flat, f"client_secret leaked in log: {event}"


# ---------------------------------------------------------------------------
# B. Integration smoke endpoint'а
# ---------------------------------------------------------------------------


class _FakeGateway(LLMGateway):
    """Замокать LLM-шлюз: либо вернуть готовый summary, либо бросить."""

    def __init__(
        self,
        *,
        result: DecisionSummary | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._result = result
        self._raises = raises
        self.calls = 0

    async def summarize(self, text: str) -> DecisionSummary:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        assert self._result is not None
        return self._result

    async def parse_search_query(
        self, text: str
    ):  # pragma: no cover — не используется в этих тестах
        raise NotImplementedError


def _decision_payload(*, source_id: str = "llm-smoke-1") -> dict[str, Any]:
    """Минимальный валидный RawDecision для /ingest."""

    return {
        "source_id": source_id,
        "source_name": "arbitr",
        "case_number": "А40-99999/2025",
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
        "participants": [],
        "norms": [],
        "full_text": "полный текст решения для саммари",
        "sections": None,
        "source_url": "https://kad.arbitr.ru/Card/yyy",
        "raw_html": None,
        "pdf_url": None,
    }


@pytest_asyncio.fixture
async def insert_decision(clean_search_tables):
    """Вставить одну CourtDecision напрямую через repository — без ES.

    /ingest требует поднятого ES; для summary это лишняя зависимость,
    тут хватает одной строки в Postgres.
    """

    from datetime import date

    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        decision = CourtDecision(
            source_id="llm-smoke-1",
            source_name="arbitr",
            case_number="А40-99999/2025",
            court_name="Арбитражный суд города Москвы",
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
            claim_amount=None,
            full_text="полный текст решения для саммари",
            sections=None,
            text_hash="a" * 64,
            source_url="https://kad.arbitr.ru/Card/yyy",
            crawled_at=datetime.now(timezone.utc),
            parsed_at=datetime.now(timezone.utc),
        )
        session.add(decision)
        await session.commit()
        await session.refresh(decision)
        decision_id = decision.id

    yield decision_id


def _override_gateway(fake: _FakeGateway) -> None:
    app.dependency_overrides[get_llm_gateway] = lambda: fake


def _clear_gateway_override() -> None:
    app.dependency_overrides.pop(get_llm_gateway, None)


@pytest.mark.asyncio
async def test_endpoint_returns_summary_for_valid_id(insert_decision) -> None:
    decision_id = insert_decision
    expected = DecisionSummary(
        summary="суть",
        key_norms=["ГК РФ ст. 506"],
        parties_brief="А vs Б",
        outcome="иск удовлетворён",
        tokens_used=128,
    )
    fake = _FakeGateway(result=expected)
    _override_gateway(fake)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/search/decisions/{decision_id}/summary"
            )
    finally:
        _clear_gateway_override()

    assert response.status_code == 200, response.text
    assert response.json() == expected.model_dump()
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_endpoint_returns_404_for_missing_id(clean_search_tables) -> None:
    fake = _FakeGateway(
        result=DecisionSummary(
            summary="x",
            key_norms=[],
            parties_brief="x",
            outcome="x",
            tokens_used=0,
        )
    )
    _override_gateway(fake)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/search/decisions/999999999/summary"
            )
    finally:
        _clear_gateway_override()

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Decision not found",
        "code": "decision_not_found",
        "field": None,
    }
    # Шлюз не должен быть вызван для несуществующего id.
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_endpoint_503_with_retry_after_on_rate_limit(insert_decision) -> None:
    """Rate-limit от LLM → 503 + Retry-After. Без него фронт может сжечь
    месячный лимит токенов одной кнопкой."""

    fake = _FakeGateway(raises=LLMRateLimitError())
    _override_gateway(fake)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/search/decisions/{insert_decision}/summary"
            )
    finally:
        _clear_gateway_override()

    assert response.status_code == 503
    assert response.headers.get("Retry-After") == "60"
    body = response.json()
    assert body["code"] == "llm_rate_limited"


@pytest.mark.asyncio
async def test_endpoint_502_on_auth_error(insert_decision) -> None:
    fake = _FakeGateway(raises=LLMAuthError())
    _override_gateway(fake)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/search/decisions/{insert_decision}/summary"
            )
    finally:
        _clear_gateway_override()

    assert response.status_code == 502
    assert response.json()["code"] == "llm_auth_error"


@pytest.mark.asyncio
async def test_endpoint_502_on_response_error(insert_decision) -> None:
    fake = _FakeGateway(raises=LLMResponseError())
    _override_gateway(fake)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/search/decisions/{insert_decision}/summary"
            )
    finally:
        _clear_gateway_override()

    assert response.status_code == 502
    assert response.json()["code"] == "llm_response_invalid"


@pytest.mark.asyncio
async def test_endpoint_504_on_timeout(insert_decision) -> None:
    fake = _FakeGateway(raises=LLMTimeoutError())
    _override_gateway(fake)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/search/decisions/{insert_decision}/summary"
            )
    finally:
        _clear_gateway_override()

    assert response.status_code == 504
    assert response.json()["code"] == "llm_timeout"
