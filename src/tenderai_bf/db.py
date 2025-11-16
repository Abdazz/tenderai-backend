"""Database connection and session management."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import settings
from .logging import get_logger

logger = get_logger(__name__)

# SQLAlchemy Base for models
Base = declarative_base()

# Global engine and session factory
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the SQLAlchemy engine."""
    global _engine
    
    if _engine is None:
        database_url = settings.get_database_url()
        
        # Engine configuration
        engine_kwargs = {
            "echo": settings.database.echo,
            "pool_size": settings.database.pool_size,
            "max_overflow": settings.database.max_overflow,
            "pool_pre_ping": True,  # Verify connections before use
            "pool_recycle": 3600,   # Recycle connections after 1 hour
        }
        
        # Use NullPool for testing to avoid connection issues
        if settings.environment == "test":
            engine_kwargs["poolclass"] = NullPool
        
        _engine = create_engine(database_url, **engine_kwargs)
        
        # Add query logging if debug mode
        if settings.debug:
            @event.listens_for(_engine, "before_cursor_execute")
            def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
                context._query_start_time = time.time()
            
            @event.listens_for(_engine, "after_cursor_execute")
            def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
                total = time.time() - context._query_start_time
                logger.debug(
                    "Database query executed",
                    query_time=total,
                    statement=statement[:200],  # Truncate long queries
                )
        
        logger.info("Database engine created", database_url=database_url.split("@")[-1])  # Hide credentials
    
    return _engine


def get_session_factory():
    """Get or create the SQLAlchemy session factory."""
    global _SessionLocal
    
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
        )
        logger.info("Database session factory created")
    
    return _SessionLocal


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Get a database session with automatic cleanup (for context manager usage)."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Database session error", error=str(e), exc_info=True)
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """Get a database session for FastAPI dependency injection."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Database session error", error=str(e), exc_info=True)
        raise
    finally:
        session.close()


def init_database():
    """Initialize the database by creating all tables."""
    from . import models  # Import models to register them
    
    engine = get_engine()
    
    try:
        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
        
        # Test connection
        with get_db_context() as session:
            session.execute(text("SELECT 1"))
            logger.info("Database connection test successful")
            
    except Exception as e:
        logger.error("Database initialization failed", error=str(e), exc_info=True)
        raise


def drop_database():
    """Drop all database tables. Use with caution!"""
    if settings.is_production:
        raise RuntimeError("Cannot drop database in production environment")
    
    from . import models  # Import models to register them
    
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    logger.error("All database tables dropped")


def check_database_health() -> bool:
    """Check if the database is healthy and accessible."""
    try:
        with get_db_context() as session:
            session.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        return False


def get_database_info() -> dict:
    """Get database connection information."""
    engine = get_engine()
    
    try:
        with get_db_context() as session:
            result = session.execute(text("SELECT version()"))
            version = result.scalar()
            
            result = session.execute(text("SELECT current_database()"))
            database_name = result.scalar()
            
            return {
                "version": version,
                "database": database_name,
                "url": str(engine.url).split("@")[-1],  # Hide credentials
                "pool_size": engine.pool.size(),
                "checked_out": engine.pool.checkedout(),
            }
    except Exception as e:
        logger.error("Failed to get database info", error=str(e))
        return {"error": str(e)}


# Import time for query timing
import time