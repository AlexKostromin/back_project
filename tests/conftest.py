from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.db import session as db_session
from app.es import client as es_client
from app.es.mapping import ensure_court_decisions_index
from app.main import app

SEARCH_TABLES = (
    "search_decision_norms",
    "search_decision_participants",
    "search_court_decisions",
)

TEST_ES_INDEX = "test_court_decisions"


@pytest.fixture(autouse=True)
def _reset_engine_cache():
    """Drop cached engine/sessionmaker between tests.

    pytest-asyncio creates a fresh event loop per test; the asyncpg pool
    bound to the previous loop becomes invalid. Clearing the caches forces
    a new engine tied to the current loop.
    """
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()
    es_client.get_es_client.cache_clear()
    yield
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()
    es_client.get_es_client.cache_clear()


@pytest_asyncio.fixture
async def clean_search_tables():
    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        for table in SEARCH_TABLES:
            await session.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
        await session.commit()
    yield


@pytest_asyncio.fixture
async def clean_es_index():
    """Route ingest/search to a dedicated test index, dropped and recreated
    fresh per test.

    Overrides ``get_settings`` on the FastAPI app so the ingest handler
    uses ``test_court_decisions`` instead of the real ``court_decisions``.
    The override is cleared in teardown so other tests that don't depend
    on this fixture are unaffected.
    """

    test_settings = Settings(es_court_decisions_index=TEST_ES_INDEX)
    app.dependency_overrides[get_settings] = lambda: test_settings

    es = es_client.get_es_client()
    await es.indices.delete(index=TEST_ES_INDEX, ignore_unavailable=True)
    await ensure_court_decisions_index(es, name=TEST_ES_INDEX)

    try:
        yield es
    finally:
        await es.indices.delete(index=TEST_ES_INDEX, ignore_unavailable=True)
        app.dependency_overrides.pop(get_settings, None)
        await es.close()
