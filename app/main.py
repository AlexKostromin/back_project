from fastapi import FastAPI, Depends
from app.core.config import get_settings, Settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version, debug=settings.app_debug)


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/health")
def health(settings: Settings = Depends(get_settings)):
    return {"status": "health", "version": settings.app_version}
