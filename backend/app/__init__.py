"""TextileSearch FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("FastAPI application starting up")
    yield
    logger.info("FastAPI application shutting down")


def create_app() -> FastAPI:
    from app.api.health      import router as health_router
    from app.api.history     import router as history_router
    from app.api.duplicates  import router as duplicates_router
    from app.api.import_ import router as import_router
    from app.api.images  import router as images_router

    app = FastAPI(
        title       = "TextileSearch Backend",
        description = "AI-powered textile image search sidecar",
        version     = "1.0.0",
        lifespan    = lifespan,
        docs_url    = "/docs",
        redoc_url   = None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins  = ["http://localhost:*", "file://"],
        allow_methods  = ["GET", "POST", "PATCH", "DELETE"],
        allow_headers  = ["*"],
    )

    app.include_router(health_router,      tags=["system"])
    app.include_router(history_router,     tags=["history"])
    app.include_router(duplicates_router,  tags=["duplicates"])
    app.include_router(import_router,  tags=["import"])
    app.include_router(images_router,  tags=["images"])

    return app
