from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_id: int
    name: str
    role: str
    inn: str | None
    ogrn: str | None


class NormResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_id: int
    law_name: str
    article: str
    part: str | None
    paragraph: str | None
    raw_ref: str | None


class DecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int

    source_id: str
    source_name: str

    case_number: str
    court_name: str
    court_type: str
    instance_level: int | None
    region: str | None

    decision_date: date
    publication_date: date | None

    doc_type: str
    judges: list[str]

    result: str | None
    appeal_status: str | None
    dispute_type: str | None
    category: str | None
    claim_amount: Decimal | None

    full_text: str
    sections: dict | None

    text_hash: str

    source_url: str
    minio_path: str | None

    es_indexed: bool
    qdrant_indexed: bool

    created_at: datetime
    updated_at: datetime

    participants: list[ParticipantResponse]
    norms: list[NormResponse]
