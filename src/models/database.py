"""Database connection and session management for Railway PostgreSQL."""

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
    """
    Build async database URL from environment.

    Railway provides DATABASE_URL as:
      postgres://user:pass@host:port/dbname
    or via individual vars:
      PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE
    """
    url = os.environ.get("DATABASE_URL", "")

    if not url:
        # Try Railway's individual PG variables
        host = os.environ.get("PGHOST", "")
        if host:
            port = os.environ.get("PGPORT", "5432")
            user = os.environ.get("PGUSER", "postgres")
            password = os.environ.get("PGPASSWORD", "")
            database = os.environ.get("PGDATABASE", "railway")
            url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
        else:
            return "postgresql+asyncpg://user:password@localhost:5432/vans_uk"

    # Railway uses postgres:// which asyncpg doesn't accept
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Railway PostgreSQL requires SSL
    if "sslmode" not in url and "ssl" not in url:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}ssl=require"

    return url


DATABASE_URL = _build_database_url()

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=5,
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
        logger.warning("Could not initialize database: %s", e)


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
