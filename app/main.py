from fastapi import Depends, FastAPI

from app.core.config import Settings, get_settings
from app.core.error_handlers import register_exception_handlers
from app.modules.search.router import router as search_router

settings = get_settings()
# NOTE: ``debug`` is intentionally NOT passed to FastAPI. With ``debug=True``
# Starlette's ``ServerErrorMiddleware`` intercepts unhandled exceptions before
# our registered ``Exception`` handler runs and returns a plain-text traceback
# to the client — violating "Never expose stack traces to clients" (CLAUDE.md).
# ``settings.app_debug`` still drives other dev-only behavior (SQL echo, etc.).
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Backend LexInsight — поиск по корпусу судебных решений. "
        "BM25 с русским анализатором, фильтры по полям дела и агрегации "
        "для юриметрии. Дополнительно: приём решений от парсеров и "
        "выдача карточки решения по id."
    ),
    openapi_tags=[
        {
            "name": "search:decisions",
            "description": "Поиск решений: BM25 + фильтры + facets.",
        },
        {
            "name": "search:ingest",
            "description": "Приём решений от парсеров.",
        },
    ],
)

register_exception_handlers(app)

app.include_router(search_router, prefix="/api/v1")


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/health")
def health(settings: Settings = Depends(get_settings)):
    return {"status": "health", "version": settings.app_version}
