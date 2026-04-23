from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CourtDecision
from app.modules.search.schemas.enums import SortBy
from app.modules.search.schemas.search import SearchDecisionsRequest


class CourtDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_text_hash(self, text_hash: str) -> CourtDecision | None:
        stmt = select(CourtDecision).where(CourtDecision.text_hash == text_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, decision_id: int) -> CourtDecision | None:
        stmt = select(CourtDecision).where(CourtDecision.id == decision_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def add(self, decision: CourtDecision) -> CourtDecision:
        self._session.add(decision)
        await self._session.flush()
        return decision

    async def search(
        self, request: SearchDecisionsRequest
    ) -> tuple[Sequence[CourtDecision], int]:
        """Return a page of decisions matching ``request`` plus total count.

        Total is computed with a separate ``COUNT(*)`` over the same WHERE
        clause — cheap on a properly indexed table and simpler than window
        functions. ES slice will take over full-text/ranking later.
        """

        conditions = self._build_conditions(request)

        total_stmt = select(func.count()).select_from(CourtDecision)
        if conditions:
            total_stmt = total_stmt.where(*conditions)
        total = (await self._session.execute(total_stmt)).scalar_one()

        stmt: Select[tuple[CourtDecision]] = select(CourtDecision)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = self._apply_sort(stmt, request.sort_by)
        stmt = stmt.offset((request.page - 1) * request.page_size).limit(
            request.page_size
        )

        result = await self._session.execute(stmt)
        return result.scalars().all(), total

    @staticmethod
    def _build_conditions(
        request: SearchDecisionsRequest,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = []

        if request.case_number is not None:
            conditions.append(CourtDecision.case_number == request.case_number)
        if request.court_type is not None:
            conditions.append(CourtDecision.court_type == request.court_type.value)
        if request.region is not None:
            conditions.append(CourtDecision.region == request.region)
        if request.doc_type is not None:
            conditions.append(CourtDecision.doc_type == request.doc_type.value)
        if request.result is not None:
            conditions.append(CourtDecision.result == request.result.value)
        if request.appeal_status is not None:
            conditions.append(
                CourtDecision.appeal_status == request.appeal_status.value
            )
        if request.dispute_type is not None:
            conditions.append(
                CourtDecision.dispute_type == request.dispute_type.value
            )

        if request.date_from is not None:
            conditions.append(CourtDecision.decision_date >= request.date_from)
        if request.date_to is not None:
            conditions.append(CourtDecision.decision_date <= request.date_to)

        if request.claim_amount_min is not None:
            conditions.append(
                CourtDecision.claim_amount >= request.claim_amount_min
            )
        if request.claim_amount_max is not None:
            conditions.append(
                CourtDecision.claim_amount <= request.claim_amount_max
            )

        return conditions

    @staticmethod
    def _apply_sort(
        stmt: Select[tuple[CourtDecision]], sort_by: SortBy
    ) -> Select[tuple[CourtDecision]]:
        if sort_by is SortBy.DATE_ASC:
            return stmt.order_by(
                CourtDecision.decision_date.asc(), CourtDecision.id.asc()
            )
        return stmt.order_by(
            CourtDecision.decision_date.desc(), CourtDecision.id.desc()
        )
