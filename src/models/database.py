"""Database connection and session management."""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


def _build_database_url() -> str:
    """Build async database URL from environment, handling Railway format."""
    url = os.environ.get("DATABASE_URL", "")

    if not url:
        # No DATABASE_URL set - use a default for local dev
        return "postgresql+asyncpg://user:password@localhost:5432/vans_uk"

    # Railway/Heroku use postgres:// which SQLAlchemy doesn't accept
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Railway requires SSL - add sslmode if not already present
    if "sslmode" not in url:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}ssl=require"

    return url


DATABASE_URL = _build_database_url()

_db_available = bool(os.environ.get("DATABASE_URL"))

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables. Logs warning and continues if DB is unreachable."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully")
    except Exception as e:
        logger.warning(
            "Could not initialize database: %s. "
            "API will start but database-dependent endpoints will fail. "
            "Ensure DATABASE_URL is set and the database is reachable.",
            e,
        )


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session."""
    session = async_session()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
