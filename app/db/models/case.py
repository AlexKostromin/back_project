from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.court_decision import CourtDecision


class Case(Base):
    """Case-level metadata shared across all decisions within the same legal case.

    One case card (e.g., on kad.arbitr.ru) can have multiple decisions
    (first-instance, appeal, cassation). This table stores the case-level
    attributes (parties, judges, dispute category) exactly once to avoid
    duplication in the :class:`CourtDecision` table.

    Coexists with denormalized fields in ``search_court_decisions`` during
    migration phase (variant B.1 from architecture decision); those fields
    will be deprecated gradually.
    """

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Source identity (where the case was crawled from)
    source_name: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Parser source: 'arbitr', 'sudrf', etc. Matches court_decisions.source_name",
    )
    external_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="External case UUID from source (e.g., KAD CaseId UUID as string)",
    )

    # Legal case identity (human-readable)
    case_number: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
        comment="Human-readable case number (e.g., 'А37-1073/2026'). NOT unique — collisions across courts",
    )
    court_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Full court name (e.g., 'Арбитражный суд города Севастополя')",
    )
    court_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Court type from CourtType enum (arbitrazh, soy, ks, vs, fas)",
    )
    court_tag: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        index=True,
        comment="KAD-specific court routing tag (e.g., 'SEVASTOPOL'). Used for jurimetric facets",
    )
    instance_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Court instance level: 1 (first), 2 (appeal), 3 (cassation), 4 (supervisory)",
    )
    region: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Region extracted from court name (fragile, TZ v1.1 requirement)",
    )
    dispute_category: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Dispute category from case card <h2> (fragile, KAD-specific)",
    )

    # Structured case data (JSONB for mutability on re-parse)
    parties: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default="[]",
        comment=(
            "List of case parties: [{name: str, role: str, inn?: str, ogrn?: str, address?: str}, ...]. "
            "PII WARNING: parties[].address contains personal data under 152-ФЗ (natural persons in bankruptcy). "
            "Must not appear in unstructured logs or unmasked API responses."
        ),
    )
    judges: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default="[]",
        comment="List of judge short names (e.g., ['Иванов И. И.', 'Петрова А. Б.'])",
    )

    # Lifecycle timestamps
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp when the case card was crawled from the source",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    decisions: Mapped[list[CourtDecision]] = relationship(
        "CourtDecision",
        back_populates="case",
        lazy="selectin",
    )

    __table_args__ = (
        # One source + external_id = one case (unique constraint)
        sa.UniqueConstraint("source_name", "external_id", name="uq_cases_source_external_id"),
        # Instance level validation (1..4)
        CheckConstraint("instance_level BETWEEN 1 AND 4", name="ck_cases_instance_level"),
    )
