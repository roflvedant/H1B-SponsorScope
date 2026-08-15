"""Create the SQLAlchemy engine and request-scoped database sessions.

The engine owns the application's PostgreSQL connection pool. ``SessionLocal``
creates short-lived units of work, while ``get_database_session`` integrates
those sessions with FastAPI's dependency system.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config.settings import DATABASE_URL


# ---------------------------------------------------------------------------
# Engine and session factory
# ---------------------------------------------------------------------------

# ``pool_pre_ping`` verifies a pooled connection before using it. This prevents
# stale connections—common after a local Docker restart or cloud database idle
# period—from causing the first request to fail unexpectedly.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

# Sessions do not automatically flush every pending change before unrelated
# queries, and stored objects remain readable after a transaction commits.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Declarative model base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Shared SQLAlchemy base inherited by every persisted model."""


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def get_database_session() -> Generator[Session, None, None]:
    """Provide one database session and always close it after the request.

    Transaction commits and rollbacks remain the repository's responsibility.
    The ``finally`` block handles connection cleanup even when an endpoint or
    repository function raises an exception.
    """

    database = SessionLocal()

    try:
        yield database
    finally:
        database.close()