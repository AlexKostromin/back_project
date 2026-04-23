from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CourtType(str, Enum):
    """Type of court."""

    ARBITRAZH = "arbitrazh"
    SOY = "soy"
    KS = "ks"
    VS = "vs"
    FAS = "fas"


class DocType(str, Enum):
    """Type of court document."""

    DECISION = "решение"
    RESOLUTION = "постановление"
    RULING = "определение"
    VERDICT = "приговор"
    LETTER = "письмо"


class ResultType(str, Enum):
    """Decision result type."""

    SATISFIED = "satisfied"
    PARTIAL = "partial"
    DENIED = "denied"
    RETURNED = "returned"
    OTHER = "other"


class AppealStatus(str, Enum):
    """Appeal status of the decision."""

    NONE = "none"
    APPEALED = "appealed"
    OVERTURNED = "overturned"
    PARTIAL_OVERTURNED = "partial_overturned"
    UPHELD = "upheld"


class DisputeType(str, Enum):
    """Type of legal dispute."""

    ADMIN = "admin"
    BANKRUPTCY = "bankruptcy"
    CIVIL = "civil"
    CRIMINAL = "criminal"


class ParticipantRole(str, Enum):
    """Role of a participant in the case."""

    PLAINTIFF = "plaintiff"
    DEFENDANT = "defendant"
    THIRD_PARTY = "third_party"
    OTHER = "other"


class SectionKey(str, Enum):
    """Keys for document sections."""

    INTRO = "intro"
    DESCRIPTIVE = "descriptive"
    MOTIVATIONAL = "motivational"
    RESOLUTIVE = "resolutive"


class Participant(BaseModel):
    """Case participant information."""

    model_config = ConfigDict(frozen=True)

    name: str
    role: ParticipantRole
    inn: str | None = None
    ogrn: str | None = None


class NormRef(BaseModel):
    """Reference to legal norm."""

    model_config = ConfigDict(frozen=True)

    law_name: str
    article: str
    part: str | None = None
    paragraph: str | None = None
    raw_ref: str


class RawDocument(BaseModel):
    """Raw unparsed document from source."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    source_name: str
    html: str | None = None
    pdf_bytes: bytes | None = None
    url: str | None = None
    crawled_at: datetime

    @model_validator(mode="after")
    def validate_content_present(self) -> RawDocument:
        """Ensure at least one of html or pdf_bytes is present."""
        if not self.html and not self.pdf_bytes:
            raise ValueError("At least one of 'html' or 'pdf_bytes' must be provided")
        return self


class ParsedDecision(BaseModel):
    """Structured decision after parsing."""

    model_config = ConfigDict(frozen=True)

    source_name: str
    source_id: str
    case_number: str
    court_name: str
    court_type: CourtType
    instance_level: int = Field(ge=1, le=4)
    region: str | None = None
    decision_date: date
    publication_date: date | None = None
    doc_type: DocType
    judges: list[str]
    result: ResultType
    appeal_status: AppealStatus = AppealStatus.NONE
    category: str | None = None
    dispute_type: DisputeType
    claim_amount: Decimal | None = None
    participants: list[Participant]
    norms: list[NormRef] = Field(default_factory=list)
    full_text: str
    sections: dict[str, str] = Field(default_factory=dict)
    text_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]+$")
    source_url: str
    minio_path: str | None = None
    crawled_at: datetime
    parsed_at: datetime
