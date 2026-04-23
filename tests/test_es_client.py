from __future__ import annotations

import pytest

from app.es import client as es_client


@pytest.fixture(autouse=True)
def _reset_es_cache():
    """Drop the cached client between tests — each test gets a fresh
    aiohttp session tied to its own event loop, mirroring the DB
    engine reset in conftest.py."""

    es_client.get_es_client.cache_clear()
    yield
    es_client.get_es_client.cache_clear()


@pytest.mark.asyncio
async def test_es_client_pings_live_cluster() -> None:
    es = es_client.get_es_client()
    try:
        assert await es.ping() is True
    finally:
        await es.close()


@pytest.mark.asyncio
async def test_es_client_cluster_health_is_reachable() -> None:
    """Beyond ping, verify we can actually read cluster health — catches
    the case where the socket is open but ES itself hasn't finished
    starting."""

    es = es_client.get_es_client()
    try:
        health = await es.cluster.health()
        assert health["status"] in {"green", "yellow", "red"}
        assert "cluster_name" in health
    finally:
        await es.close()
