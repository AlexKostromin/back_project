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
