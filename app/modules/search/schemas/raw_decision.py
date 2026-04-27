from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.modules.search.schemas.enums import (
    AppealStatus,
    CourtType,
    DecisionResult,
    DisputeType,
    DocType,
    ParticipantRole,
    SourceName,
)


class RawParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=1024)
    role: ParticipantRole
    inn: str | None = Field(default=None, max_length=12)
    ogrn: str | None = Field(default=None, max_length=15)


class RawNorm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    law_name: str = Field(min_length=1, max_length=256)
    article: str = Field(min_length=1, max_length=64)
    part: str | None = Field(default=None, max_length=64)
    paragraph: str | None = Field(default=None, max_length=64)
    raw_ref: str = Field(min_length=1, max_length=512)


class RawSections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intro: str | None = None
    descriptive: str | None = None
    motivational: str | None = None
    resolutive: str | None = None


class RawDecision(BaseModel):
    """Входной контракт со стороны парсера.

    Парсер обязан выдавать объекты, соответствующие этой схеме. Любое
    расхождение — это нарушение контракта; его нужно ловить на этапе
    приёма, а не где-то дальше в пайплайне.
    """

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=256)
    source_name: SourceName
    case_number: str = Field(min_length=1, max_length=256)
    court_name: str = Field(min_length=1, max_length=512)
    court_type: CourtType
    instance_level: int | None = Field(default=None, ge=1, le=4)
    region: str | None = Field(default=None, max_length=256)

    decision_date: date
    publication_date: date | None = None

    doc_type: DocType
    judges: list[str] = Field(default_factory=list)

    result: DecisionResult | None = None
    appeal_status: AppealStatus | None = None
    dispute_type: DisputeType | None = None
    category: str | None = Field(default=None, max_length=256)
    claim_amount: Decimal | None = Field(default=None, ge=0)

    participants: list[RawParticipant] = Field(default_factory=list)
    norms: list[RawNorm] = Field(default_factory=list)

    full_text: str = Field(min_length=1, max_length=10_000_000)
    sections: RawSections | None = None

    source_url: HttpUrl
    raw_html: str | None = Field(default=None, max_length=20_000_000)
    pdf_url: HttpUrl | None = None
