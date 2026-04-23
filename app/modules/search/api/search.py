from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.modules.search.schemas.search import (
    SearchDecisionsRequest,
    SearchDecisionsResponse,
)
from app.modules.search.services.search import SearchService

router = APIRouter(prefix="/decisions", tags=["search:decisions"])


@router.post(
    "",
    response_model=SearchDecisionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Search court decisions by SQL filters (ES-ranked search comes later)",
)
async def search_decisions(
    request: SearchDecisionsRequest,
    session: AsyncSession = Depends(get_session),
) -> SearchDecisionsResponse:
    service = SearchService(session)
    return await service.search(request)
