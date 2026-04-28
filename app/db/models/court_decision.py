from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.case import Case
    from app.db.models.decision_norm import DecisionNorm
    from app.db.models.decision_participant import DecisionParticipant


class CourtDecision(Base):
    __tablename__ = "search_court_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    case_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("cases.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="FK to cases table. NULL during migration phase (coexistence period)",
    )

    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(String(20), nullable=False)

    case_number: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    court_name: Mapped[str] = mapped_column(Text, nullable=False)
    court_type: Mapped[str] = mapped_column(String(20), nullable=False)
    instance_level: Mapped[int] = mapped_column(nullable=False)
    region: Mapped[str | None] = mapped_column(Text, nullable=True)

    decision_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    judges: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    result: Mapped[str] = mapped_column(String(30), nullable=False)
    appeal_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=sa.text("'none'")
    )
    dispute_type: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    sections: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    minio_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    es_indexed: Mapped[bool] = mapped_column(default=False, nullable=False)
    qdrant_indexed: Mapped[bool] = mapped_column(default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    case: Mapped[Case | None] = relationship(
        "Case",
        back_populates="decisions",
        lazy="selectin",
    )
    participants: Mapped[list[DecisionParticipant]] = relationship(
        back_populates="decision",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    norms: Mapped[list[DecisionNorm]] = relationship(
        back_populates="decision",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
