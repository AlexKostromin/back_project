from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class RawDecision(BaseModel):
    """Raw unparsed decision from source."""

    model_config = ConfigDict(frozen=True)

    source: str
    source_id: str
    url: str | None
    raw_content: str
    fetched_at: datetime


class ParsedDecision(BaseModel):
    """Structured decision after parsing."""

    model_config = ConfigDict(frozen=True)

    source: str
    source_id: str
    case_number: str
    court_name: str
    judges: list[str]
    decision_date: date
    category: str | None
    result: str | None
    appeal_status: str | None
    participants: list[str]
    full_text: str
    url: str | None
    fetched_at: datetime
    parsed_at: datetime
