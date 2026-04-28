from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from pydantic import ValidationError

from app.core.config import Settings
from app.llm.exceptions import (
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.llm.gateway import LLMGateway
from app.modules.search.schemas.search import SearchDecisionsRequest
from app.modules.search.schemas.summary import DecisionSummary

log = structlog.get_logger(__name__)


# System prompt для GigaChat-Lite. Жёстко требуем чистый JSON, без
# код-блоков и пояснений — иначе придётся регуляркой выгрызать
# ```json ... ```. Структура полей зафиксирована в DecisionSummary.
_SYSTEM_PROMPT = (
    "Ты — юридический ассистент. Получая текст судебного решения, "
    "возвращаешь СТРОГО валидный JSON со следующими полями: "
    'summary (2-3 предложения, суть спора и итог), '
    'key_norms (массив строк с нормами вида "ГК РФ ст. 506"), '
    'parties_brief (одной строкой: истец vs ответчик), '
    'outcome (одной строкой: что присудил суд). '
    "Не добавляй пояснений, не оборачивай в код-блоки, только JSON."
)

# Запас, на сколько секунд раньше "официального" expires_at мы считаем
# токен невалидным. Защита от race на границе TTL: сетевая задержка
# + clock skew легко съедают пару секунд, поэтому 60 — практичный буфер.
_TOKEN_REFRESH_LEEWAY_SECONDS = 60


# System prompt для NLQ-парсера. Жёстко перечисляем все допустимые
# поля и enum-значения — без этого LLM с радостью галлюцинирует
# "court_type": "верховный" и валится на ValidationError. Маппинги
# семантики собраны из реальных юридических формулировок, чтобы
# покрыть бытовой язык юриста ("истец выиграл", "налоговые споры").
_NLQ_SYSTEM_PROMPT = (
    "Ты — парсер юридических поисковых запросов. Получая фразу "
    "пользователя, возвращаешь СТРОГО валидный JSON со структурой:\n\n"
    "{\n"
    '  "query": <строка|null>,           '
    "// ключевые слова для полнотекстового поиска (без имён сторон, без дат)\n"
    '  "court_type": <enum|null>,        '
    '// допустимо: "arbitrazh", "soy", "ks", "vs", "fas"\n'
    '  "region": <строка|null>,          '
    '// например: "Москва", "Санкт-Петербург"\n'
    '  "doc_type": <enum|null>,          '
    "// допустимо: "
    '"решение", "постановление", "определение", "приговор", "письмо", '
    '"особое_мнение"\n'
    '  "dispute_type": <enum|null>,      '
    '// допустимо: "admin", "civil", "bankruptcy", "criminal"\n'
    '  "result": <enum|null>,            '
    '// допустимо: "satisfied", "partial", "denied", "returned", "other"\n'
    '  "appeal_status": <enum|null>,     '
    '// допустимо: "appealed", "overturned", "partial_overturned", '
    '"upheld", "none"\n'
    '  "case_number": <строка|null>,     '
    '// например: "А40-12345/2025"\n'
    '  "date_from": <YYYY-MM-DD|null>,\n'
    '  "date_to": <YYYY-MM-DD|null>,\n'
    '  "claim_amount_min": <число|null>,\n'
    '  "claim_amount_max": <число|null>,\n'
    '  "sort_by": <"relevance"|"date_desc"|"date_asc">  '
    "// если запрос содержит ключевые слова — "
    '"relevance", иначе "date_desc"\n'
    "}\n\n"
    "Маппинг семантики:\n"
    '- "истец/работник/налогоплательщик выиграл" → result="satisfied"\n'
    '- "проиграл/отказали" → result="denied"\n'
    '- "налоговые споры" → dispute_type="admin"\n'
    '- "о банкротстве" → dispute_type="bankruptcy"\n'
    '- "арбитражные суды/АС" → court_type="arbitrazh"\n'
    '- "СОЮ/районный суд/мировой суд" → court_type="soy"\n'
    '- "за 2025" → date_from="2025-01-01", date_to="2025-12-31"\n'
    "- если поле непонятно — оставляй null, не угадывай.\n\n"
    "Не добавляй пояснений, не оборачивай в код-блоки, только JSON."
)


class GigaChatAdapter(LLMGateway):
    """Адаптер LLMGateway поверх GigaChat (Сбер).

    Архитектурные решения:

    - **OAuth2 client credentials** на ``ngw.devices.sberbank.ru``
      выдаёт короткоживущий ``access_token`` (минуты), который
      нужно класть в ``Authorization: Bearer ...`` для chat API
      на ``gigachat.devices.sberbank.ru``. Токен кэшируем в инстансе
      адаптера и обновляем под ``asyncio.Lock`` (двойная проверка),
      чтобы параллельные запросы не били ``/oauth`` десятком запросов
      одновременно.

    - **TLS**: цепочка GigaChat подписана Russian Trusted Root CA,
      которой нет в стандартном бандле ``certifi``. Поэтому
      ``verify=settings.gigachat_ca_bundle_path`` — иначе httpx
      откажется устанавливать соединение.

    - **Truncation**: ``gigachat_max_input_chars`` — жёсткий cap,
      чтобы не выйти за context window ``GigaChat`` (Lite). Логируем
      WARNING при срезании, но не падаем — лучше получить чуть
      обрезанное саммари, чем 400-ку.

    - **Retry на 401**: один раз пробуем с обновлённым токеном (на
      случай, если кэшированный токен внезапно отозвали серверной
      стороной). Второй 401 — уже LLMAuthError, не зацикливаемся.

    - **Без retry на 429**: на demo-тарифе rate-limit обычно означает
      исчерпание месячного лимита токенов, retry бесполезен. Клиент
      получит 503 и сам решит, ждать или нет.
    """

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        if http_client is not None:
            self._http = http_client
            self._owns_http = False
        else:
            self._http = httpx.AsyncClient(
                verify=settings.gigachat_ca_bundle_path,
                timeout=settings.gigachat_request_timeout_s,
            )
            self._owns_http = True

        self._access_token: str | None = None
        self._expires_at: datetime | None = None
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Закрыть внутренний httpx-клиент, если адаптер его создавал.

        Если клиент пришёл извне (например, в тестах) — не трогаем,
        владение не наше.
        """

        if self._owns_http:
            await self._http.aclose()

    async def summarize(self, text: str) -> DecisionSummary:
        """Сгенерировать ``DecisionSummary`` через chat completions.

        Полный путь: truncate → ensure-token → POST /chat/completions
        → parse JSON-content → validate Pydantic → tokens_used.
        """

        truncated = self._truncate_input(text)

        payload = self._build_chat_payload(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=f"Текст решения:\n\n{truncated}",
            temperature=0.2,
        )
        started = time.perf_counter()
        data = await self._chat_with_token_refresh(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        summary = self._parse_summary(data)

        log.info(
            "llm.summarize",
            prompt_hash=_hash_for_audit(truncated),
            tokens_used=summary.tokens_used,
            latency_ms=latency_ms,
            model=self._settings.gigachat_model,
        )
        return summary

    async def parse_search_query(
        self, text: str
    ) -> tuple[SearchDecisionsRequest, int]:
        """Распарсить натуральный текст в ``SearchDecisionsRequest``.

        Контракт отличается от ``summarize`` одним важным моментом: на
        «частичное понимание» (LLM вернул не-JSON или невалидный набор
        полей) мы НЕ raise'им ``LLMResponseError``. NLQ — это UX-слой,
        и для пользователя лучше показать выдачу по degraded-фильтру
        ``query=text``, чем 502. Auth/rate/timeout/сетевые сбои
        по-прежнему улетают как ``LLMError``-семья и маппятся в 502/503/504.
        """

        # Cap уже стоит в Pydantic-схеме (max_length=512), но если
        # gateway дёрнут напрямую — пусть страховка тоже отрабатывает.
        truncated = self._truncate_input(text)
        text_hash = _hash_for_audit(truncated)

        payload = self._build_chat_payload(
            system_prompt=_NLQ_SYSTEM_PROMPT,
            user_prompt=f"Запрос пользователя:\n\n{truncated}",
            # Низкая температура: парсер должен быть детерминированным,
            # одинаковый текст → одинаковый JSON. Креативность тут
            # вредит, она же провоцирует галлюцинации в enum-полях.
            temperature=0.1,
        )
        started = time.perf_counter()
        data = await self._chat_with_token_refresh(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        try:
            content = data["choices"][0]["message"]["content"]
            total_tokens = int(data["usage"]["total_tokens"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            # Контракт самой OpenAI-обёртки нарушен — это уже не
            # «LLM не понял», это сломанный провайдер. 502.
            raise LLMResponseError(
                "LLM response is missing required fields"
            ) from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            log.warning(
                "nlq.parse_failed",
                reason="non_json",
                text_hash=text_hash,
                tokens_used=total_tokens,
                latency_ms=latency_ms,
            )
            return self._nlq_fallback(truncated), total_tokens

        if not isinstance(parsed, dict):
            log.warning(
                "nlq.parse_failed",
                reason="non_object",
                text_hash=text_hash,
                tokens_used=total_tokens,
                latency_ms=latency_ms,
            )
            return self._nlq_fallback(truncated), total_tokens

        try:
            request = SearchDecisionsRequest.model_validate(parsed)
        except ValidationError:
            log.warning(
                "nlq.parse_failed",
                reason="validation",
                text_hash=text_hash,
                tokens_used=total_tokens,
                latency_ms=latency_ms,
            )
            return self._nlq_fallback(truncated), total_tokens

        # Логируем только имена заполненных фильтров — по ним строим
        # аналитику «что именно люди ищут», без утечки самого текста.
        filled = sorted(
            name
            for name, value in request.model_dump(exclude_none=True).items()
            if name not in {"sort_by", "page", "page_size"}
        )
        log.info(
            "nlq.parsed",
            parsed_filters=filled,
            tokens_used=total_tokens,
            latency_ms=latency_ms,
            text_hash=text_hash,
            model=self._settings.gigachat_model,
        )
        return request, total_tokens

    # ------------------------------------------------------------------
    # Внутренние помощники
    # ------------------------------------------------------------------

    def _truncate_input(self, text: str) -> str:
        cap = self._settings.gigachat_max_input_chars
        if len(text) <= cap:
            return text
        log.warning(
            "llm.input_truncated",
            original_len=len(text),
            truncated_to=cap,
        )
        return text[:cap]

    def _build_chat_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> dict:
        """Собрать chat-completions payload.

        Параметризован system/user/temperature, потому что ``summarize``
        и ``parse_search_query`` отличаются именно этими тремя
        параметрами, а каркас (модель, формат сообщений) одинаковый.
        """

        return {
            "model": self._settings.gigachat_model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

    async def _chat_with_token_refresh(self, payload: dict) -> dict:
        """POST /chat/completions с одним retry на 401 и маппингом ошибок.

        Выделено в общий helper, чтобы и ``summarize``, и
        ``parse_search_query`` одинаково обрабатывали:

        * 401 — один retry с принудительным refresh токена; повторный
          401 → ``LLMAuthError``.
        * 429 → ``LLMRateLimitError`` (без ретраев — на demo-тарифе
          это месячный лимит, ждать бесполезно).
        * любые ``>=400`` → ``LLMError``.
        * timeout → ``LLMTimeoutError``.
        * любой другой transport-сбой httpx → ``LLMError``.

        Возвращает уже распарсенный JSON-словарь ответа; не лезет в
        ``choices[0]`` — это специфично для каждого вызова.
        """

        token = await self._get_token()

        try:
            response = await self._post_chat(token, payload)
            if response.status_code == 401:
                # Один retry с принудительным refresh — токен мог
                # быть отозван между нашим кэшем и запросом.
                token = await self._get_token(force_refresh=True)
                response = await self._post_chat(token, payload)
                if response.status_code == 401:
                    raise LLMAuthError("LLM auth failed after token refresh")
            if response.status_code == 429:
                raise LLMRateLimitError("LLM rate limit exceeded")
            if response.status_code >= 400:
                raise LLMError(
                    f"LLM provider returned status {response.status_code}"
                )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("LLM request timed out") from exc
        except httpx.HTTPError as exc:
            # Сетевые/транспортные сбои httpx (DNS, connection reset,
            # SSL handshake) — это всё провайдер недоступен.
            raise LLMError("LLM transport error") from exc

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise LLMResponseError("LLM returned non-JSON body") from exc

    @staticmethod
    def _nlq_fallback(text: str) -> SearchDecisionsRequest:
        """Degraded-парсинг для NLQ: ``query=text``, дефолтная сортировка.

        Используется, когда LLM вернула не-JSON или JSON, не
        проходящий валидацию схемы. Цель — отдать пользователю хоть
        какой-то результат BM25-поиска по его же исходной фразе,
        вместо того чтобы швырнуть 502 в UI.
        """

        return SearchDecisionsRequest(query=text)

    async def _post_chat(
        self,
        token: str,
        payload: dict,
    ) -> httpx.Response:
        return await self._http.post(
            f"{self._settings.gigachat_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
        )

    def _parse_summary(self, data: dict) -> DecisionSummary:
        """Распарсить chat-completions ответ → ``DecisionSummary``.

        Контракт OpenAI-совместимый: ``choices[0].message.content``
        — это строка с JSON, который мы и просили в system-prompt.
        ``usage.total_tokens`` подкидываем уже после валидации, чтобы
        LLM не мог подменить нам поле аудита.
        """

        try:
            content = data["choices"][0]["message"]["content"]
            total_tokens = int(data["usage"]["total_tokens"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMResponseError(
                "LLM response is missing required fields"
            ) from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                "LLM content is not valid JSON"
            ) from exc

        if not isinstance(parsed, dict):
            raise LLMResponseError("LLM content is not a JSON object")

        # tokens_used кладём из usage, не из content — иначе LLM
        # "галлюцинирует" любое число.
        parsed["tokens_used"] = total_tokens

        try:
            return DecisionSummary.model_validate(parsed)
        except ValidationError as exc:
            raise LLMResponseError(
                "LLM content failed schema validation"
            ) from exc

    async def _get_token(self, *, force_refresh: bool = False) -> str:
        """Вернуть валидный access_token, обновив при необходимости.

        Двойная проверка под lock: первый thread заходит в lock,
        обновляет токен; следующие, дождавшись lock, видят свежий
        токен и не делают лишний OAuth-запрос.
        """

        if not force_refresh and self._token_is_fresh():
            assert self._access_token is not None  # noqa: S101 — guarded by check
            return self._access_token

        async with self._token_lock:
            if not force_refresh and self._token_is_fresh():
                assert self._access_token is not None  # noqa: S101
                return self._access_token

            token, expires_at = await self._fetch_token()
            self._access_token = token
            self._expires_at = expires_at
            return token

    def _token_is_fresh(self) -> bool:
        if self._access_token is None or self._expires_at is None:
            return False
        return datetime.now(timezone.utc) < self._expires_at

    async def _fetch_token(self) -> tuple[str, datetime]:
        """OAuth2 client_credentials → ``(access_token, expires_at)``.

        ``RqUID`` обязателен — Сбер использует его как correlation id
        и без него отдаёт 400. Клиентские credentials уходят в
        ``Authorization: Basic`` и НИКОГДА не логируются.
        """

        client_id = self._settings.gigachat_client_id
        client_secret = self._settings.gigachat_client_secret
        basic = base64.b64encode(
            f"{client_id}:{client_secret}".encode("utf-8")
        ).decode("ascii")

        try:
            response = await self._http.post(
                self._settings.gigachat_auth_url,
                headers={
                    "Authorization": f"Basic {basic}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={"scope": self._settings.gigachat_scope},
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("LLM auth request timed out") from exc
        except httpx.HTTPError as exc:
            raise LLMError("LLM auth transport error") from exc

        if response.status_code == 401:
            raise LLMAuthError("invalid client credentials")
        if response.status_code == 429:
            raise LLMRateLimitError("LLM auth rate limit exceeded")
        if response.status_code >= 400:
            raise LLMError(
                f"LLM auth returned status {response.status_code}"
            )

        try:
            data = response.json()
            access_token = data["access_token"]
            expires_at_ms = int(data["expires_at"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise LLMResponseError("LLM auth response malformed") from exc

        # Сбер отдаёт expires_at как UNIX ms. Минусуем leeway, чтобы
        # не упереться в просрочку прямо в момент запроса.
        expires_at = datetime.fromtimestamp(
            expires_at_ms / 1000, tz=timezone.utc
        ) - timedelta(seconds=_TOKEN_REFRESH_LEEWAY_SECONDS)
        return access_token, expires_at


def _hash_for_audit(text: str) -> str:
    """SHA-256 от первых 200 символов — для ``prompt_hash`` в логах.

    Полный prompt не пишем: даже на публичных решениях это раздувает
    лог-объём и засоряет ELK. Хеш достаточен для группировки повторов.
    """

    return hashlib.sha256(text[:200].encode("utf-8")).hexdigest()
