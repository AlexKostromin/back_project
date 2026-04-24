import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import get_settings, Settings


@pytest.fixture
def override_settings():
    fake = Settings(app_name="Test", app_version="9.9.9", app_debug=True)
    app.dependency_overrides[get_settings] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_health_returns_version_from_settings(override_settings):
    transport = ASGITransport(app=app)
    async with AsyncClient(
            transport=transport,
            base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "health", "version": "9.9.9"}


@pytest.mark.asyncio
async def test_root_returns_ok():
    transport = ASGITransport(app=app)
    async with AsyncClient(
            transport=transport,
            base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_openapi_exposes_search_request_examples() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()

    schemas = spec["components"]["schemas"]
    search_request = schemas["SearchDecisionsRequest"]
    examples = search_request.get("examples")

    assert examples is not None, "SearchDecisionsRequest must expose Swagger examples"
    assert len(examples) == 4

    summaries = {e["summary"] for e in examples}
    assert summaries == {
        "Filter-only default",
        "Relevance search",
        "Narrow by court + period",
        "Combined query and filters",
    }
