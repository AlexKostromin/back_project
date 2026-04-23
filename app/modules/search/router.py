from __future__ import annotations

from fastapi import APIRouter

from app.modules.search.api.decisions import router as decisions_router
from app.modules.search.api.ingest import router as ingest_router

router = APIRouter(prefix="/search")
router.include_router(ingest_router)
router.include_router(decisions_router)
