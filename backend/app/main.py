"""FastAPI Application Entry Point for GeoRoute AI Backend Service."""

from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import health, routes
from app.config import settings
from app.jobs.job_executor import JobExecutor
from app.jobs.job_store import JobStore
from app.schemas.api_schemas import ErrorResponse
from app.services.orchestrator import PipelineOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("georoute.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manages application lifecycle initialization and resource cleanup."""
    logger.info("Initializing GeoRoute AI API service...")
    settings.ensure_directories()

    # Initialize persistence, domain orchestrator, and worker executor
    job_store = JobStore(settings.sqlite_db_path)
    orchestrator = PipelineOrchestrator(job_store=job_store)
    job_executor = JobExecutor(job_store=job_store, orchestrator=orchestrator)

    app.state.job_store = job_store
    app.state.orchestrator = orchestrator
    app.state.job_executor = job_executor

    logger.info("GeoRoute AI service initialization complete.")
    yield

    logger.info("Shutting down GeoRoute AI service...")
    job_executor.shutdown(wait=False)
    logger.info("GeoRoute AI service shutdown complete.")


def create_app() -> FastAPI:
    """Factory function creating the configured FastAPI application instance."""
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Terrain-aware railway corridor planning API utilizing multi-objective "
            "friction surface modeling and PYORPS Cython shortest-path optimization."
        ),
        lifespan=lifespan,
    )

    # CORS Middleware
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins if settings.cors_origins != ["*"] else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global Exception Handlers
    @application.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code", "HTTP_ERROR")
            message = detail.get("message", str(detail))
            details = detail
        else:
            code = "HTTP_ERROR"
            message = str(detail)
            details = None

        payload = ErrorResponse(code=code, message=message, details=details)
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled exception on request {request.method} {request.url}: {exc}")
        payload = ErrorResponse(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal server error occurred.",
            details={"error_type": type(exc).__name__},
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=payload.model_dump())

    # Include Routers
    application.include_router(health.router, prefix=settings.api_prefix)
    application.include_router(routes.router, prefix=settings.api_prefix)

    # Top-level index route
    @application.get("/", tags=["System & Diagnostics"])
    async def root_index():
        return {
            "app": settings.app_name,
            "version": settings.app_version,
            "docs_url": "/docs",
            "api_prefix": settings.api_prefix,
            "status": "online",
        }

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
