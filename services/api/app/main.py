"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app_core.settings import get_api_settings, get_shared_settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.corrections import router as corrections_router
from app.routers.documents import router as documents_router
from app.routers.search import router as search_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail fast: a misconfigured env should crash at boot, not on first request.
    get_api_settings()
    get_shared_settings()
    yield


def create_app() -> FastAPI:
    settings = get_api_settings()
    app = FastAPI(
        title="Document Intelligence API",
        version="0.1.0",
        docs_url="/docs",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(documents_router)
    app.include_router(search_router)
    app.include_router(corrections_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
