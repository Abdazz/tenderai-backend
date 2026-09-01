"""Structured logging configuration using structlog."""

import logging
import logging.config
import os
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.types import FilteringBoundLogger

from .config import settings


def configure_logging() -> FilteringBoundLogger:
    """Configure structured logging for the application."""

    # Determine logs directory.
    # Use /app/logs in containerised deployments; fall back to a local or temp path otherwise.
    _app_logs = Path("/app/logs")
    if _app_logs.parent.exists():
        logs_dir = _app_logs
    else:
        logs_dir = Path("logs")

    # In test environments, use a temp directory to avoid permission issues with
    # log files that may be owned by a different user from a previous run.
    _use_file_logging = settings.environment != "test"
    if _use_file_logging:
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            # Probe write access
            for log_file in ["tenderai.log", "error.log"]:
                log_path = logs_dir / log_file
                if not log_path.exists():
                    log_path.touch()
                    log_path.chmod(0o666)
                elif not os.access(log_path, os.W_OK):
                    _use_file_logging = False
                    break
        except PermissionError:
            _use_file_logging = False

    # Build handlers dict; always include console, optionally include file handlers.
    _handlers: dict = {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "colored" if sys.stdout.isatty() else "json",
        },
    }
    _active_handlers = ["console"]
    if _use_file_logging:
        _handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(logs_dir / "tenderai.log"),
            "maxBytes": 10 * 1024 * 1024,  # 10MB
            "backupCount": 5,
            "formatter": "json",
        }
        _handlers["error_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(logs_dir / "error.log"),
            "maxBytes": 10 * 1024 * 1024,  # 10MB
            "backupCount": 5,
            "formatter": "json",
            "level": "ERROR",
        }
        _active_handlers = ["console", "file", "error_file"]

    # Configure standard logging
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.dev.ConsoleRenderer(colors=False),
                "foreign_pre_chain": [
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.add_logger_name,
                    structlog.processors.TimeStamper(fmt="iso"),
                ],
            },
            "colored": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.dev.ConsoleRenderer(colors=True),
                "foreign_pre_chain": [
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.add_logger_name,
                    structlog.processors.TimeStamper(fmt="iso"),
                ],
            },
        },
        "handlers": _handlers,
        "loggers": {
            "": {
                "handlers": _active_handlers,
                "level": settings.monitoring.log_level,
                "propagate": False,
            },
            "tenderai": {
                "handlers": _active_handlers,
                "level": settings.monitoring.log_level,
                "propagate": False,
            },
            # Third-party library log levels
            "httpx": {
                "handlers": ["file"] if _use_file_logging else ["console"],
                "level": "WARNING",
                "propagate": False,
            },
            "sqlalchemy.engine": {
                "handlers": ["file"] if _use_file_logging else ["console"],
                "level": "WARNING" if not settings.database.echo else "INFO",
                "propagate": False,
            },
            "alembic": {
                "handlers": ["console"] + (["file"] if _use_file_logging else []),
                "level": "INFO",
                "propagate": False,
            },
        },
    }

    logging.config.dictConfig(logging_config)

    # Configure structlog
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.is_development:
        # Development: pretty console output
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        # Production: JSON output
        structlog.configure(
            processors=[*shared_processors, structlog.processors.JSONRenderer()],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    # Return configured logger
    logger = structlog.get_logger("tenderai")

    # Log startup information
    logger.info(
        "Logging configured",
        environment=settings.environment,
        log_level=settings.monitoring.log_level,
        app_version=settings.app_version,
    )

    return logger


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Get a logger instance for a specific module."""
    _ensure_logging_configured()
    return structlog.get_logger(name or "tenderai")


def log_run_start(run_id: str, **kwargs) -> None:
    """Log the start of a pipeline run."""
    logger = get_logger("pipeline")
    logger.info("Pipeline run started", run_id=run_id, event_type="run_start", **kwargs)


def log_run_complete(
    run_id: str,
    duration: float,
    stats: dict[str, Any],
    **extra: Any,
) -> None:
    """Log the completion of a pipeline run.

    Extra keyword arguments are merged with the stats dict so callers can
    attach run-level context (e.g. ``status``, ``warnings_count``) without
    bloating ``RunStatistics``.
    """
    logger = get_logger("pipeline")
    logger.info(
        "Pipeline run completed",
        run_id=run_id,
        duration_seconds=duration,
        event_type="run_complete",
        **stats,
        **extra,
    )


def log_run_error(run_id: str, error: Exception, **kwargs) -> None:
    """Log a pipeline run error."""
    logger = get_logger("pipeline")
    logger.error(
        "Pipeline run failed",
        run_id=run_id,
        error=str(error),
        error_type=type(error).__name__,
        event_type="run_error",
        exc_info=True,
        **kwargs,
    )


def log_source_fetch(source_name: str, url: str, status: str, **kwargs) -> None:
    """Log source fetching activity."""
    logger = get_logger("fetcher")
    logger.info(
        "Source fetch",
        source_name=source_name,
        url=url,
        status=status,
        event_type="source_fetch",
        **kwargs,
    )


def log_classification(
    notice_id: str, score: float, is_relevant: bool, **kwargs
) -> None:
    """Log classification results."""
    logger = get_logger("classifier")
    logger.info(
        "Notice classified",
        notice_id=notice_id,
        relevance_score=score,
        is_relevant=is_relevant,
        event_type="classification",
        **kwargs,
    )


def log_email_sent(recipient: str, status: str, **kwargs) -> None:
    """Log email sending activity."""
    logger = get_logger("email")
    logger.info(
        "Email sent",
        recipient=recipient,
        status=status,
        event_type="email_sent",
        **kwargs,
    )


def log_metrics(metrics: dict[str, Any]) -> None:
    """Log application metrics."""
    logger = get_logger("metrics")
    logger.info("Application metrics", event_type="metrics", **metrics)


class MetricsCollector:
    """Simple metrics collector for Prometheus-style metrics."""

    def __init__(self):
        self.counters: dict[str, int] = {}
        self.gauges: dict[str, float] = {}
        self.histograms: dict[str, list] = {}

    def increment(self, name: str, value: int = 1, **labels) -> None:
        """Increment a counter metric."""
        key = self._make_key(name, labels)
        self.counters[key] = self.counters.get(key, 0) + value

    def set_gauge(self, name: str, value: float, **labels) -> None:
        """Set a gauge metric."""
        key = self._make_key(name, labels)
        self.gauges[key] = value

    def observe_histogram(self, name: str, value: float, **labels) -> None:
        """Add an observation to a histogram."""
        key = self._make_key(name, labels)
        if key not in self.histograms:
            self.histograms[key] = []
        self.histograms[key].append(value)

    def _make_key(self, name: str, labels: dict[str, Any]) -> str:
        """Create a metric key from name and labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def export_metrics(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []

        # Export counters
        for key, value in self.counters.items():
            lines.append(f"# TYPE {key.split('{')[0]} counter")
            lines.append(f"{key} {value}")

        # Export gauges
        for key, value in self.gauges.items():
            lines.append(f"# TYPE {key.split('{')[0]} gauge")
            lines.append(f"{key} {value}")

        # Export histograms (simplified)
        for key, values in self.histograms.items():
            if values:
                base_name = key.split("{")[0]
                lines.append(f"# TYPE {base_name} histogram")
                lines.append(f"{key}_count {len(values)}")
                lines.append(f"{key}_sum {sum(values)}")
                if values:
                    lines.append(f"{key}_avg {sum(values) / len(values)}")

        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all metrics."""
        self.counters.clear()
        self.gauges.clear()
        self.histograms.clear()


# Global metrics collector
metrics = MetricsCollector()

# Logger instance - configure logging on first import
# This is safe because get_logger() will call structlog.get_logger()
# which doesn't require configure_logging() to be called first
_configured = False


def _ensure_logging_configured():
    """Ensure logging is configured before use."""
    global _configured
    if not _configured:
        configure_logging()
        _configured = True
