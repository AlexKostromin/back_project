from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from elasticsearch import AsyncElasticsearch

from app.core.config import get_settings


@lru_cache
def get_es_client() -> AsyncElasticsearch:
    """Return the process-wide async Elasticsearch client.

    Cached so every repo/service reuses one connection pool. ES client is
    thread-/task-safe and manages its own aiohttp pool — creating one per
    request (like we do for SQLAlchemy sessions) would be wasteful.
    """

    settings = get_settings()
    return AsyncElasticsearch(
        hosts=[settings.es_url],
        request_timeout=settings.es_request_timeout_s,
        # Retry on connection errors so a short ES restart doesn't turn into
        # a user-facing 500; ES GETs are idempotent, retry is safe.
        max_retries=2,
        retry_on_timeout=True,
    )


async def get_es() -> AsyncIterator[AsyncElasticsearch]:
    """FastAPI dependency wrapper around the cached client.

    Yields the same shared client — there's no per-request teardown for
    ES. The dependency exists so route handlers can depend on
    ``AsyncElasticsearch`` via ``Depends(get_es)`` just like they
    depend on ``AsyncSession`` via ``Depends(get_session)``.
    """

    yield get_es_client()
