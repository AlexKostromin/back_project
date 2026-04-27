from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.search.schemas.enums import (
    AppealStatus,
    CourtType,
    DecisionResult,
    DisputeType,
    DocType,
    SortBy,
)


class _DecisionsFilter(BaseModel):
    """Общий набор фильтров для POST /decisions (поиск) и /decisions/facets.

    Все поля здесь транслируются в ES bool/filter плюс опциональный
    multi_match в must. Конкретные запросы поверх добавляют свои
    дополнительные поля (пагинация, сортировка и т. п.).
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "summary": "По умолчанию: только фильтры",
                    "description": (
                        "Без полнотекстового запроса, сортировка по "
                        "умолчанию (дата по убыванию), первая страница "
                        "из 20 элементов."
                    ),
                    "value": {},
                },
                {
                    "summary": "Поиск по релевантности",
                    "description": (
                        "BM25 по `full_text`/`court_name`/`category` с "
                        "русским анализатором. Сортировка по `_score`."
                    ),
                    "value": {
                        "query": "налог",
                        "sort_by": "relevance",
                        "page_size": 5,
                    },
                },
                {
                    "summary": "Сужение по суду и периоду",
                    "description": (
                        "Чисто фильтровой запрос — арбитражные суды "
                        "Москвы за 2025 календарный год."
                    ),
                    "value": {
                        "court_type": "arbitrazh",
                        "region": "Москва",
                        "date_from": "2025-01-01",
                        "date_to": "2025-12-31",
                    },
                },
                {
                    "summary": "Запрос вместе с фильтрами",
                    "description": (
                        "Полнотекстовый запрос 'поставка' среди "
                        "арбитражных дел, ранжирование по релевантности. "
                        "Демонстрирует чистое сочетание `must` и `filter`."
                    ),
                    "value": {
                        "query": "поставка",
                        "court_type": "arbitrazh",
                        "sort_by": "relevance",
                    },
                },
            ]
        },
    )

    query: str | None = Field(default=None, min_length=1, max_length=512)

    case_number: str | None = Field(default=None, min_length=1, max_length=256)
    court_type: CourtType | None = None
    region: str | None = Field(default=None, min_length=1, max_length=256)
    doc_type: DocType | None = None
    result: DecisionResult | None = None
    appeal_status: AppealStatus | None = None
    dispute_type: DisputeType | None = None

    date_from: date | None = None
    date_to: date | None = None

    claim_amount_min: Decimal | None = Field(default=None, ge=0)
    claim_amount_max: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_ranges(self) -> Self:
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must be <= date_to")
        if (
            self.claim_amount_min is not None
            and self.claim_amount_max is not None
            and self.claim_amount_min > self.claim_amount_max
        ):
            raise ValueError("claim_amount_min must be <= claim_amount_max")
        return self


class SearchDecisionsRequest(_DecisionsFilter):
    """Запрос поиска судебных решений на базе Elasticsearch.

    Наследует общий набор фильтров (полнотекстовый запрос плюс
    точные/диапазонные предикаты) от :class:`_DecisionsFilter` и
    добавляет пагинацию и сортировку. Поле ``query`` — необязательный
    полнотекстовый запрос, который сопоставляется с ``full_text``,
    ``court_name`` и ``category`` (с бустами на уровне полей);
    ``None`` означает «только фильтры». Пустые строки отвергаются,
    чтобы клиент случайно не отправил пустой поиск. Facets и
    предикаты по участникам/нормам появятся в следующих слайсах.
    """

    # Pydantic v2 merges model_config across inheritance, but re-declaring
    # it here makes the contract explicit at the leaf class.
    model_config = ConfigDict(extra="forbid")

    sort_by: SortBy = Field(
        default=SortBy.DATE_DESC,
        description=(
            "`relevance` требует непустой `query`, иначе у всех "
            "документов одинаковый score и порядок теряет смысл."
        ),
    )

    page: int = Field(
        default=1,
        ge=1,
        le=100,
        description=(
            "Номер страницы (от 1). Ограничен 100, чтобы оставаться "
            "ниже ES `index.max_result_window`=10000 при "
            "`page_size=100`. Для более глубоких результатов "
            "используйте более узкие фильтры или (в будущем) "
            "`search_after`."
        ),
    )
    page_size: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def _validate_relevance_requires_query(self) -> Self:
        if self.sort_by is SortBy.RELEVANCE and self.query is None:
            raise ValueError("sort_by=relevance requires query")
        return self


class FacetsRequest(_DecisionsFilter):
    """Запрос агрегаций: тот же набор фильтров, без пагинации и сортировки.

    Пагинация для агрегаций бессмысленна — всегда возвращаем top-K
    бакетов по каждому facet. Сортировка тоже не нужна: бакеты
    упорядочены по своему естественному ключу (count по убыванию для
    terms, хронологически для date_histogram).
    """

    # No extra fields — intentionally empty. Kept as a distinct class so
    # the OpenAPI schema and Pydantic errors point at "FacetsRequest",
    # which matches the route name and helps clients.


class DecisionListItem(BaseModel):
    """Облегчённая проекция судебного решения для списка.

    Опускает тяжёлые поля (`full_text`, `sections`, `raw_html`) и
    внутренние флаги. Поле ``snippet`` — первый highlight-фрагмент ES
    по ``full_text``, когда сработал полнотекстовый запрос; иначе
    подставляются первые ~300 символов ``full_text``, чтобы у ответов
    «только по фильтрам» всё равно был превью.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_number: str
    court_name: str
    court_type: str
    region: str | None
    decision_date: date
    doc_type: str
    result: str | None
    appeal_status: str | None
    dispute_type: str | None
    claim_amount: Decimal | None
    snippet: str


class SearchDecisionsResponse(BaseModel):
    """Постраничный ответ поиска: метаданные пагинации и список решений."""

    model_config = ConfigDict(extra="forbid")

    total: int
    page: int
    page_size: int
    items: list[DecisionListItem]


class FacetBucket(BaseModel):
    """Одна строка terms-агрегации."""

    model_config = ConfigDict(extra="forbid")

    key: str
    count: int


class MonthBucket(BaseModel):
    """Одна строка date_histogram ``decisions_by_month``."""

    model_config = ConfigDict(extra="forbid")

    month: date  # first day of the month (ES returns ms epoch; we parse)
    count: int


class FacetsResponse(BaseModel):
    """Ответ с агрегациями: счётчики по основным фильтрам и распределение по месяцам."""

    model_config = ConfigDict(extra="forbid")

    total: int
    court_type: list[FacetBucket]
    dispute_type: list[FacetBucket]
    result: list[FacetBucket]
    region: list[FacetBucket]
    decisions_by_month: list[MonthBucket]
