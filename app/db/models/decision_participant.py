from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.court_decision import CourtDecision


class DecisionParticipant(Base):
    __tablename__ = "search_decision_participants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("search_court_decisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    inn: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    ogrn: Mapped[str | None] = mapped_column(String(15), nullable=True)

    decision: Mapped[CourtDecision] = relationship(back_populates="participants")
