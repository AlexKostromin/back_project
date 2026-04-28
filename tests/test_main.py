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
    # Pydantic v2 + FastAPI разделяет схему на ``*-Input`` и ``*-Output``,
    # если она появляется и как request body (POST /decisions), и как
    # часть response model'а (NLQResponse.parsed_query из POST /decisions/nlq).
    # Examples мы фиксируем именно на input-стороне — это то, что юзер шлёт.
    search_request = schemas.get(
        "SearchDecisionsRequest-Input"
    ) or schemas["SearchDecisionsRequest"]
    examples = search_request.get("examples")

    assert examples is not None, "SearchDecisionsRequest must expose Swagger examples"
    assert len(examples) == 4

    summaries = {e["summary"] for e in examples}
    assert summaries == {
        "По умолчанию: только фильтры",
        "Поиск по релевантности",
        "Сужение по суду и периоду",
        "Запрос вместе с фильтрами",
    }
