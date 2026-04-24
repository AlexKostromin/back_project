from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.parsers.schemas import CourtType, ParticipantRole


class KadParty(BaseModel):
    """Сторона в карточке дела (Кредитор/Должник/Третье лицо/Иные)."""

    model_config = ConfigDict(frozen=True)

    name: str
    role: ParticipantRole
    inn: str | None = None
    ogrn: str | None = None
    # PII risk under 152-ФЗ when party is a natural person (common in банкротство).
    # Must not appear in unstructured logs or unmasked API responses.
    address: str | None = None


class DocumentRef(BaseModel):
    """Ссылка на документ из b-case-chrono-ed-item — будем скачивать в Stage 3d."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    document_date: date
    document_type: str | None = None
    url: str | None = None
    description: str | None = None


class KadCaseSummary(BaseModel):
    """Сводка по карточке дела kad.arbitr.ru. Не путать с CourtDecision/ParsedDecision."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    case_number: str
    court_name: str
    court_type: CourtType
    instance_level: int = Field(ge=1, le=4)
    region: str | None = None
    dispute_category: str | None = None
    parties: list[KadParty] = Field(default_factory=list)
    judges: list[str] = Field(default_factory=list)
    document_refs: list[DocumentRef] = Field(default_factory=list)
    source_url: str
    crawled_at: datetime

    @field_validator("source_url")
    @classmethod
    def _http_scheme_only(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("source_url must start with http:// or https://")
        return v
