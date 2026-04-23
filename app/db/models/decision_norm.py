from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.court_decision import CourtDecision


class DecisionNorm(Base):
    __tablename__ = "search_decision_norms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("search_court_decisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    law_name: Mapped[str] = mapped_column(Text, nullable=False)
    article: Mapped[str] = mapped_column(Text, nullable=False)
    part: Mapped[str | None] = mapped_column(Text, nullable=True)
    paragraph: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_ref: Mapped[str | None] = mapped_column(Text, nullable=True)

    decision: Mapped[CourtDecision] = relationship(back_populates="norms")
