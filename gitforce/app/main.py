from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gitforce.app.api.routes import (
    dashboard,
    evaluation,
    health,
    metrics,
    security,
    tasks,
)
from gitforce.app.api.websocket import router as websocket_router
from gitforce.app.config.settings import get_settings
from gitforce.app.observability.middleware import ObservabilityMiddleware
from gitforce.app.observability.tracing import init_tracing
from gitforce.app.security.rate_limit import RateLimitMiddleware

logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    from gitforce.app.security.logging import configure_logging
    from gitforce.app.security.secrets import SecretManager

    configure_logging(structured=settings.structured_logging)
    if settings.enable_secret_management:
        SecretManager().register()
    logger.info("Starting Gitforce in %s mode", settings.env)
    init_tracing()
    logger.info("Observability initialized")
    if settings.is_development:
        from gitforce.app.database import models
        from gitforce.app.database.session import engine

        async with engine.begin() as conn:
            await conn.run_sync(models.Base.metadata.create_all)
        logger.info("Database schema ensured")
    yield
    logger.info("Shutting down Gitforce")


def create_app() -> FastAPI:
    get_settings()
    app = FastAPI(
        title="Gitforce",
        description="Autonomous, Human-Governed Software Engineering Agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(RateLimitMiddleware)

    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(evaluation.router)
    app.include_router(metrics.router)
    app.include_router(dashboard.router)
    app.include_router(security.router)
    app.include_router(websocket_router)

    # Frontend (section 5): serve the static SPA.
    static_dir = FRONTEND_DIR
    if static_dir.exists():
        app.mount(
            "/static", StaticFiles(directory=str(static_dir)), name="static"
        )

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(str(static_dir / "index.html"))

        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon() -> FileResponse:
            svg = static_dir / "favicon.svg"
            if svg.exists():
                return FileResponse(str(svg), media_type="image/svg+xml")
            return FileResponse(str(static_dir / "index.html"))

    return app


app = create_app()
