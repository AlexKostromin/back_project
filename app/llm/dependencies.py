from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.llm.adapters.gigachat import GigaChatAdapter
from app.llm.gateway import LLMGateway


@lru_cache
def get_llm_gateway() -> LLMGateway:
    """FastAPI dependency: процесс-широкий ``LLMGateway``.

    Кэшируется через ``lru_cache`` — нам нужен ровно один инстанс
    адаптера на процесс, потому что:

    1. В нём живёт кэш OAuth-токена. Создавать новый адаптер на
       каждый запрос — это новый OAuth-роунд каждый раз, что съедает
       лимит и добавляет ~200 мс латентности.
    2. ``httpx.AsyncClient`` внутри адаптера держит connection pool;
       пересоздавать его per-request убивает keep-alive.

    Тесты с pytest-asyncio могут получать "залипший" клиент с прошлого
    event-loop'а — для этого ниже есть ``_clear_llm_gateway_cache``,
    которым conftest.py будет сбрасывать кэш между тестами.
    """

    settings = get_settings()
    return GigaChatAdapter(settings)


def _clear_llm_gateway_cache() -> None:
    """Сбросить ``lru_cache`` адаптера. Использовать только в тестах.

    pytest-asyncio пересоздаёт event-loop между тестами, и у
    кэшированного ``httpx.AsyncClient`` остаётся ссылка на старый
    loop — в новом он падает. Очистка кэша даёт fresh-инстанс.
    """

    get_llm_gateway.cache_clear()
