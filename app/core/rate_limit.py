"""Per-IP rate-limit для LLM-эндпоинтов.

Зачем: ``POST /decisions/{id}/summary`` и ``POST /decisions/nlq`` дёргают
GigaChat. На demo-тарифе ``GIGACHAT_API_PERS`` месячный лимит токенов
конечен. Открытый анонимный эндпоинт без лимита один curl-цикл (или
просто бот-сканнер) сжигает за минуты — фича возвращает 503, демонстрация
рассыпается. Лимитер закрывает этот класс рисков плотно.

Дизайн:

- ``slowapi`` поверх ``limits``: in-memory storage хватает для одного
  uvicorn-воркера (наш VPS-deploy именно такой). При горизонтальном
  масштабировании заменим storage на Redis в одну строку — лимитер
  один на процесс, поэтому держим его как module-level singleton.

- Ключ — IP клиента через ``slowapi.util.get_remote_address``. Для
  будущего reverse-proxy этот хелпер подхватывает ``X-Forwarded-For``
  если оно есть.

- Лимит читается из ``Settings.llm_rate_limit_per_minute`` —
  меняется без ребилда через ``.env``.

- Использование в роутах:
  ::

      from app.core.rate_limit import llm_limiter

      @router.post("/decisions/{decision_id}/summary")
      @llm_limiter.limit(_per_minute_limit())
      async def handler(request: Request, ...): ...

  ``request: Request`` обязан быть в сигнатуре — slowapi достаёт из
  него IP клиента через свой middleware.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import get_settings


def _per_minute_limit() -> str:
    """Динамический лимит из Settings — slowapi принимает callable.

    Делаем callable, а не константу, чтобы тесты могли подменить
    ``Settings.llm_rate_limit_per_minute`` на маленькое значение
    (например, 2) и не ждать минуту в каждом тесте.
    """

    return f"{get_settings().llm_rate_limit_per_minute}/minute"


# Module-level singleton: ровно один Limiter на процесс. И ``app.main``
# (для install_rate_limiter), и endpoint-файлы (для декоратора)
# импортируют именно его — иначе декораторы ходят в один лимитер,
# а middleware в другой, и состояние счётчиков расходится.
llm_limiter = Limiter(key_func=get_remote_address)


def install_rate_limiter(app: FastAPI) -> None:
    """Подключить ``llm_limiter`` к приложению + handler 429.

    ``slowapi`` требует, чтобы лимитер лежал в ``app.state.limiter`` —
    middleware и декоратор ``limiter.limit`` ходят туда. Handler
    переопределяем на наш формат ``{detail, code, field}`` (как у
    ``AppError``), чтобы ответы 429 не отличались по схеме от
    остальных ошибок.
    """

    app.state.limiter = llm_limiter
    app.add_exception_handler(RateLimitExceeded, _handle_rate_limit_exceeded)


async def _handle_rate_limit_exceeded(
    request: Request,
    exc: RateLimitExceeded,
) -> JSONResponse:
    """Ответ 429 с ``Retry-After: 60`` и единым JSON-форматом.

    ``slowapi`` сам по себе уже ставит ``Retry-After`` через свой
    middleware, но мы делаем JSON-тело руками, чтобы фронт мог рендерить
    тем же кодом, что и наши ``AppError``-ответы (см.
    ``app/core/error_handlers.py``: ``{detail, code, field}``).
    """

    return JSONResponse(
        status_code=429,
        content={
            "detail": "Слишком много запросов к LLM-эндпоинту, попробуйте позже",
            "code": "rate_limit_exceeded",
            "field": None,
        },
        headers={"Retry-After": "60"},
    )
