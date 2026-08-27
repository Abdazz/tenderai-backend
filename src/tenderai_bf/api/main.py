"""FastAPI application for TenderAI BF."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from ..config import settings
from ..logging import get_logger
from .routers import admin, countries, health, recipients, reports, runs, sources, users

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """FastAPI lifespan events."""

    # Startup
    logger.info(
        "Starting FastAPI application",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )

    # Initialize database
    from ..db import check_database_health, init_database

    try:
        init_database()
        if check_database_health():
            logger.info("Database connection established")
        else:
            logger.error("Database health check failed")
    except Exception as e:
        logger.error("Failed to initialize database", error=str(e))

    # Initialize storage
    from ..storage import get_storage_client

    try:
        storage_client = get_storage_client()
        if storage_client.health_check():
            logger.info("Storage connection established")
        else:
            logger.error("Storage health check failed")
    except Exception as e:
        logger.error("Failed to initialize storage", error=str(e))

    # Seed settings from current config if DB is empty, then seed all countries
    try:
        from ..country_store import CountryStore
        from ..db import get_session_factory
        from ..models import Country as CountryModel
        from ..settings_store import SettingsStore

        SessionLocal = get_session_factory()  # noqa: N806 — SQLAlchemy idiom for a session factory
        with SessionLocal() as db_session:
            seeded = SettingsStore.seed_from_settings(db_session)
            if seeded:
                logger.info("Settings seeded from config", sections=seeded)

            # Seed country_settings for every active country that is missing rows
            countries = (
                db_session.query(CountryModel)
                .filter(
                    CountryModel.active == True  # noqa: E712
                )
                .all()
            )
            for country in countries:
                seeded_cs = CountryStore.seed_from_global(db_session, country.id)
                if seeded_cs:
                    logger.info(
                        "Country settings seeded",
                        country_code=country.code,
                        sections=seeded_cs,
                    )
    except Exception as e:
        logger.warning("Could not seed settings from DB", error=str(e))

    yield

    # Shutdown
    logger.info("Shutting down FastAPI application")


# Create FastAPI app
app = FastAPI(
    title="TenderAI BF API",
    description="Multi-agent RFP harvester for Burkina Faso - REST API",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Add middlewares
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handle uncaught exceptions."""

    logger.error(
        "Unhandled exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=exc,
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error": str(exc) if settings.debug else "An error occurred",
        },
    )


# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(runs.router, prefix="/api/v1/runs", tags=["Runs"])
app.include_router(sources.router, prefix="/api/v1/sources", tags=["Sources"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(recipients.router, prefix="/api/v1/recipients", tags=["Recipients"])
app.include_router(
    countries.router, prefix="/api/v1/admin/countries", tags=["Countries"]
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "tenderai_bf.api.main:app",
        host="0.0.0.0",  # noqa: S104 — dev-only entrypoint; production runs via uvicorn/Docker with proper network config
        port=8000,
        reload=settings.debug,
        log_level="info",
    )
