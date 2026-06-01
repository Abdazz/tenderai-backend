"""FastAPI application for TenderAI BF."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from ..config import settings
from ..logging import get_logger
from .routers import health, runs, sources, reports, admin, users, countries

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """FastAPI lifespan events."""
    
    # Startup
    logger.info(
        "Starting FastAPI application",
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment
    )
    
    # Initialize database
    from ..db import init_database, check_database_health
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

    # Seed settings from current config if DB is empty
    try:
        from ..db import get_session_factory
        from ..settings_store import SettingsStore
        from ..config import reload_settings_from_db
        SessionLocal = get_session_factory()
        db_session = SessionLocal()
        try:
            seeded = SettingsStore.seed_from_settings(db_session)
            if seeded:
                logger.info("Settings seeded from config", sections=seeded)
            reload_settings_from_db(db_session)
            logger.info("Settings loaded from DB")
        finally:
            db_session.close()
    except Exception as e:
        logger.warning("Could not seed/reload settings from DB", error=str(e))

    # Seed BF country if no countries exist yet
    try:
        from ..models import Country as CountryModel
        from ..country_store import CountryStore as CS
        db_session2 = SessionLocal()
        try:
            if not db_session2.query(CountryModel).first():
                bf = CountryModel(name="Burkina Faso", code="BF", locale="fr", active=True)
                db_session2.add(bf)
                db_session2.commit()
                db_session2.refresh(bf)
                CS.seed_from_global(db_session2, bf.id)
                logger.info("Seeded Burkina Faso as default country")
        finally:
            db_session2.close()
    except Exception as e:
        logger.warning("Could not seed BF country", error=str(e))

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
    openapi_url="/openapi.json"
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
        exc_info=exc
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error": str(exc) if settings.debug else "An error occurred"
        }
    )


# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(runs.router, prefix="/api/v1/runs", tags=["Runs"])
app.include_router(sources.router, prefix="/api/v1/sources", tags=["Sources"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(countries.router, prefix="/api/v1/admin/countries", tags=["Countries"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "tenderai_bf.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="info"
    )