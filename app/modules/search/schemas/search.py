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


class SearchDecisionsRequest(BaseModel):
    """Elasticsearch-backed search request for court decisions.

    ``query`` is an optional full-text query matched against ``full_text``,
    ``court_name`` and ``category`` (with field-level boosts). ``None``
    means "no text query, filter-only" — empty strings are rejected so
    callers don't accidentally send a blank search. The remaining fields
    are exact-match / range filters that map onto ES ``term``/``range``
    clauses. Facets and participant/norm predicates come in a later slice.
    """

    model_config = ConfigDict(extra="forbid")

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

    sort_by: SortBy = Field(
        default=SortBy.DATE_DESC,
        description=(
            "`relevance` requires a non-empty `query`, otherwise every "
            "document has the same score and the order is meaningless."
        ),
    )

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

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

    @model_validator(mode="after")
    def _validate_relevance_requires_query(self) -> Self:
        if self.sort_by is SortBy.RELEVANCE and self.query is None:
            raise ValueError("sort_by=relevance requires query")
        return self


class DecisionListItem(BaseModel):
    """Lightweight list-item projection of a court decision.

    Omits heavy fields (`full_text`, `sections`, `raw_html`) and internal
    flags. ``snippet`` is the first ES highlight fragment on ``full_text``
    when a text query matched; otherwise it falls back to the first
    ~300 chars of ``full_text`` so filter-only responses still render
    a preview.
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
    model_config = ConfigDict(extra="forbid")

    total: int
    page: int
    page_size: int
    items: list[DecisionListItem]
