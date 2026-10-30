"""FastAPI application entry point: `uvicorn backend.main:app`."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.api import assistant, automation, documents, interventions, reports
from backend.config import get_settings
from backend.database import init_db, session_scope
from backend.logging_config import configure_logging
from backend.services.document_service import index_pending_documents
from backend.services.errors import ServiceError
from backend.services.seed_service import register_sample_manuals, seed_reference_data

logger = logging.getLogger("backend")


def _index_documents_in_background() -> threading.Thread:
    def run() -> None:
        try:
            count = index_pending_documents(get_settings())
            logger.info("background indexing finished", extra={"documents": count})
        except Exception:
            logger.exception("background indexing failed")

    thread = threading.Thread(target=run, name="document-indexer", daemon=True)
    thread.start()
    return thread


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.api_key:
        logger.error("API_KEY is not set: every /api endpoint will answer 503 until it is configured")
    settings.ensure_directories()
    init_db()
    if settings.seed_on_startup:
        with session_scope() as db:
            seed_reference_data(db, settings.sample_data_dir)
            register_sample_manuals(db, settings)
    # Indexing may download the embedding model on first run, so it must not block startup.
    indexer = _index_documents_in_background() if settings.index_on_startup else None
    logger.info("application started", extra={"demo_mode": settings.demo_mode, "ai_enabled": settings.ai_enabled})
    yield
    if indexer is not None:
        indexer.join(timeout=10)


def create_app() -> FastAPI:
    app = FastAPI(
        title="VINCI Facilities AI Demo - API",
        description="Prototype indépendant : API de l'assistant intelligent de maintenance des bâtiments.",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):  # noqa: ANN001, ANN202
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    @app.exception_handler(ServiceError)
    async def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, **exc.details})

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(interventions.router)
    app.include_router(reports.router)
    app.include_router(assistant.router)
    app.include_router(documents.router)
    app.include_router(automation.status_router)
    app.include_router(automation.n8n_router)
    return app


app = create_app()
