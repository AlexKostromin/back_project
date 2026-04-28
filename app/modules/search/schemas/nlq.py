from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.modules.search.schemas.search import (
    SearchDecisionsRequest,
    SearchDecisionsResponse,
)


class NLQRequest(BaseModel):
    """Входной запрос NLQ-парсера: натуральный текст пользователя.

    Натурально-языковой поиск принимает свободную фразу вида
    «налоговые споры в Москве за 2025 где истец выиграл» и через LLM
    переводит её в структурный :class:`SearchDecisionsRequest`. Сам
    параметр ``text`` интенционально один — никаких побочных полей
    клиент сюда не подсовывает (``extra="forbid"``).
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"text": "налоговые споры в Москве за 2025 где истец выиграл"},
                {"text": "арбитражные дела о банкротстве"},
                {"text": "трудовые споры где работник выиграл"},
            ]
        },
    )

    text: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description=(
            "Натуральный текст запроса. Cap 512 символов: защита от "
            "prompt injection и от траты токенов на эссе."
        ),
    )


class NLQResponse(BaseModel):
    """Ответ NLQ: что LLM поняла + результаты поиска.

    Возвращаем сразу два артефакта:

    * ``parsed_query`` — структурный запрос, который фронт может
      показать пользователю «вот как я понял ваш текст», с
      возможностью править отдельные поля и переотправить уже на
      ``POST /decisions``.
    * ``results`` — собственно выдача по этому распарсенному запросу,
      контракт совпадает с обычным поиском, чтобы UI рендерил тем же
      компонентом.
    """

    model_config = ConfigDict(extra="forbid")

    parsed_query: SearchDecisionsRequest = Field(
        ...,
        description=(
            "Структурный запрос, в который LLM перевела ваш текст. "
            "Фронт показывает пользователю, чтобы он мог поправить, "
            "если что-то не так."
        ),
    )
    results: SearchDecisionsResponse = Field(
        ...,
        description=(
            "Результаты поиска по parsed_query. Контракт совпадает с "
            "POST /decisions."
        ),
    )
    tokens_used: int = Field(
        ...,
        ge=0,
        description=(
            "Сколько токенов LLM истратила на парсинг запроса "
            "(служебное поле для аудита расхода)."
        ),
    )
