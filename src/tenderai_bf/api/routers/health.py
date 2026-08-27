"""Health check and monitoring endpoints."""


from fastapi import APIRouter, status
from pydantic import BaseModel

from ...config import settings
from ...db import check_database_health, get_database_info
from ...logging import get_logger
from ...storage import get_storage_client

logger = get_logger(__name__)

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    version: str
    environment: str
    components: dict[str, dict]


class LivenessResponse(BaseModel):
    """Liveness probe response."""

    status: str


class ReadinessResponse(BaseModel):
    """Readiness probe response."""

    status: str
    ready: bool
    checks: dict[str, bool]


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Comprehensive health check endpoint.

    Returns health status of all components.
    """

    components = {}

    # Check database
    try:
        db_healthy = check_database_health()
        db_info = get_database_info()
        components["database"] = {
            "status": "healthy" if db_healthy else "unhealthy",
            "url": db_info.get("url", "unknown"),
            "pool_size": db_info.get("pool_size", 0),
        }
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        components["database"] = {"status": "unhealthy", "error": str(e)}

    # Check storage
    try:
        storage_client = get_storage_client()
        storage_healthy = storage_client.health_check()
        components["storage"] = {
            "status": "healthy" if storage_healthy else "unhealthy",
            "endpoint": settings.minio.endpoint,
            "bucket": settings.minio.bucket_name,
        }
    except Exception as e:
        logger.error("Storage health check failed", error=str(e))
        components["storage"] = {"status": "unhealthy", "error": str(e)}

    # Check email
    try:
        from ...email import test_email_configuration

        email_configured = test_email_configuration()
        components["email"] = {
            "status": "configured" if email_configured else "not_configured",
            "smtp_server": f"{settings.smtp.host}:{settings.smtp.port}",
        }
    except Exception as e:
        logger.error("Email health check failed", error=str(e))
        components["email"] = {"status": "not_configured", "error": str(e)}

    # Overall status
    critical_components = ["database", "storage"]
    overall_healthy = all(
        components.get(comp, {}).get("status") == "healthy"
        for comp in critical_components
    )

    return HealthResponse(
        status="healthy" if overall_healthy else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        components=components,
    )


@router.get(
    "/health/live", response_model=LivenessResponse, status_code=status.HTTP_200_OK
)
async def liveness_probe():
    """Liveness probe for Kubernetes/Docker.

    Returns 200 if application is running.
    """
    return LivenessResponse(status="alive")


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness_probe():
    """Readiness probe for Kubernetes/Docker.

    Returns 200 if application is ready to serve traffic.
    """

    checks = {}

    # Check database
    try:
        checks["database"] = check_database_health()
    except Exception as e:
        logger.debug("Database readiness check failed", error=str(e))
        checks["database"] = False

    # Check storage
    try:
        storage_client = get_storage_client()
        checks["storage"] = storage_client.health_check()
    except Exception as e:
        logger.debug("Storage readiness check failed", error=str(e))
        checks["storage"] = False

    ready = all(checks.values())

    return ReadinessResponse(
        status="ready" if ready else "not_ready", ready=ready, checks=checks
    )


@router.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics endpoint.

    Returns basic metrics in Prometheus format.
    """

    from ...db import get_database_info

    metrics_output = []

    # Application info
    metrics_output.append("# HELP tenderai_info Application information")
    metrics_output.append("# TYPE tenderai_info gauge")
    metrics_output.append(
        f'tenderai_info{{version="{settings.app_version}",environment="{settings.environment}"}} 1'
    )

    # Database metrics
    try:
        db_info = get_database_info()
        metrics_output.append(
            "# HELP tenderai_db_pool_size Database connection pool size"
        )
        metrics_output.append("# TYPE tenderai_db_pool_size gauge")
        metrics_output.append(f'tenderai_db_pool_size {db_info.get("pool_size", 0)}')
    except Exception as e:
        logger.debug("Failed to collect DB pool metrics", error=str(e))

    # Health status
    try:
        db_healthy = 1 if check_database_health() else 0
        metrics_output.append("# HELP tenderai_db_health Database health status")
        metrics_output.append("# TYPE tenderai_db_health gauge")
        metrics_output.append(f"tenderai_db_health {db_healthy}")
    except Exception as e:
        logger.debug("Failed to collect DB health metric", error=str(e))

    return "\n".join(metrics_output) + "\n"
