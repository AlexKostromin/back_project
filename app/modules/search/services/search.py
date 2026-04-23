from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CourtDecision
from app.modules.search.repositories.court_decision import CourtDecisionRepository
from app.modules.search.schemas.search import (
    DecisionListItem,
    SearchDecisionsRequest,
    SearchDecisionsResponse,
)

SNIPPET_LEN = 300


class SearchService:
    """SQL-only decisions search.

    Full-text ranking and highlighting will move to Elasticsearch in a later
    slice. For now: filter in WHERE, paginate, sort by decision_date, and
    build a cheap snippet from the first ``SNIPPET_LEN`` chars of full_text.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._repo = CourtDecisionRepository(session)

    async def search(
        self, request: SearchDecisionsRequest
    ) -> SearchDecisionsResponse:
        decisions, total = await self._repo.search(request)
        return SearchDecisionsResponse(
            total=total,
            page=request.page,
            page_size=request.page_size,
            items=[self._to_item(d) for d in decisions],
        )

    @staticmethod
    def _to_item(decision: CourtDecision) -> DecisionListItem:
        snippet = decision.full_text[:SNIPPET_LEN]
        return DecisionListItem(
            id=decision.id,
            case_number=decision.case_number,
            court_name=decision.court_name,
            court_type=decision.court_type,
            region=decision.region,
            decision_date=decision.decision_date,
            doc_type=decision.doc_type,
            result=decision.result,
            appeal_status=decision.appeal_status,
            dispute_type=decision.dispute_type,
            claim_amount=decision.claim_amount,
            snippet=snippet,
        )
