from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db import session as db_session

SEARCH_TABLES = (
    "search_decision_norms",
    "search_decision_participants",
    "search_court_decisions",
)


@pytest.fixture(autouse=True)
def _reset_engine_cache():
    """Drop cached engine/sessionmaker between tests.

    pytest-asyncio creates a fresh event loop per test; the asyncpg pool
    bound to the previous loop becomes invalid. Clearing the caches forces
    a new engine tied to the current loop.
    """
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()
    yield
    db_session.get_engine.cache_clear()
    db_session.get_sessionmaker.cache_clear()


@pytest_asyncio.fixture
async def clean_search_tables():
    sessionmaker = db_session.get_sessionmaker()
    async with sessionmaker() as session:
        for table in SEARCH_TABLES:
            await session.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))
        await session.commit()
    yield
