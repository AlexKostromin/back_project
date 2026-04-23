from __future__ import annotations

from fastapi import APIRouter

from app.modules.search.api.ingest import router as ingest_router

router = APIRouter(prefix="/search")
router.include_router(ingest_router)
