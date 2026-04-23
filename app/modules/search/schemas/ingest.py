from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class IngestStatus(StrEnum):
    CREATED = "created"
    DUPLICATE = "duplicate"


class IngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: IngestStatus
    decision_id: int | None = None
    text_hash: str
