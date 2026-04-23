from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.es import client as es_client
from app.es.mapping import (
    court_decisions_mappings,
    court_decisions_settings,
    ensure_court_decisions_index,
)


@pytest.fixture(autouse=True)
def _reset_es_cache():
    es_client.get_es_client.cache_clear()
    yield
    es_client.get_es_client.cache_clear()


@pytest_asyncio.fixture
async def unique_index_name():
    """Unique per-test index name so parallel / repeated runs don't
    collide. The `ensure_court_decisions_index(name=...)` hook exists
    precisely so tests can isolate themselves; production always uses
    the default constant."""

    name = f"test_court_decisions_{uuid.uuid4().hex[:8]}"
    yield name

    # Teardown: always drop the test index, even if the test created
    # it partially. ignore_unavailable lets the cleanup be idempotent.
    es = es_client.get_es_client()
    try:
        await es.indices.delete(index=name, ignore_unavailable=True)
    finally:
        await es.close()


@pytest.mark.asyncio
async def test_ensure_index_creates_when_missing(unique_index_name: str) -> None:
    es = es_client.get_es_client()
    created = await ensure_court_decisions_index(es, name=unique_index_name)
    assert created is True

    exists = await es.indices.exists(index=unique_index_name)
    assert bool(exists) is True


@pytest.mark.asyncio
async def test_ensure_index_is_idempotent(unique_index_name: str) -> None:
    es = es_client.get_es_client()
    first = await ensure_court_decisions_index(es, name=unique_index_name)
    second = await ensure_court_decisions_index(es, name=unique_index_name)
    third = await ensure_court_decisions_index(es, name=unique_index_name)

    assert first is True
    assert second is False
    assert third is False


@pytest.mark.asyncio
async def test_mapping_has_expected_shape(unique_index_name: str) -> None:
    """Spot-check the mapping actually lands with the analyzer,
    keyword subfields, and nested objects we specified. Cheap safety
    net against someone silently editing mapping.py and breaking
    search/filter behavior."""

    es = es_client.get_es_client()
    await ensure_court_decisions_index(es, name=unique_index_name)

    response = await es.indices.get_mapping(index=unique_index_name)
    props = response[unique_index_name]["mappings"]["properties"]

    assert props["full_text"]["type"] == "text"
    assert props["full_text"]["analyzer"] == "russian_text"

    assert props["case_number"]["type"] == "keyword"
    assert props["court_type"]["type"] == "keyword"

    assert props["court_name"]["type"] == "text"
    assert props["court_name"]["fields"]["raw"]["type"] == "keyword"

    assert props["decision_date"]["type"] == "date"
    assert props["claim_amount"]["type"] == "scaled_float"

    assert props["participants"]["type"] == "nested"
    assert props["participants"]["properties"]["inn"]["type"] == "keyword"

    assert props["norms"]["type"] == "nested"
    assert props["norms"]["properties"]["article"]["type"] == "keyword"


@pytest.mark.asyncio
async def test_settings_declare_russian_analyzer(unique_index_name: str) -> None:
    es = es_client.get_es_client()
    await ensure_court_decisions_index(es, name=unique_index_name)

    response = await es.indices.get_settings(index=unique_index_name)
    analyzers = response[unique_index_name]["settings"]["index"]["analysis"]["analyzer"]
    assert "russian_text" in analyzers
    assert analyzers["russian_text"]["type"] == "russian"


def test_mapping_module_is_pure() -> None:
    """The mapping builders should be pure functions — no I/O, just
    dict literals. If someone adds a side effect, this test keeps
    them honest."""

    assert court_decisions_settings() == court_decisions_settings()
    assert court_decisions_mappings() == court_decisions_mappings()
