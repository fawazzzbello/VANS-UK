"""Database connection and session management for Railway PostgreSQL."""

import logging
import os
import re
import ssl
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


def _build_database_url() -> tuple[str, dict]:
    """
    Build async database URL and connect_args from environment.

    Railway provides DATABASE_URL as:
      postgres://user:pass@host:port/dbname?sslmode=require
    or via individual vars: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE

    asyncpg does NOT support the 'sslmode' query parameter — SSL must be
    passed via connect_args. This function strips sslmode from the URL and
    returns an appropriate connect_args dict instead.
    """
    url = os.environ.get("DATABASE_URL", "")
    connect_args: dict = {}

    if not url:
        host = os.environ.get("PGHOST", "")
        if host:
            port = os.environ.get("PGPORT", "5432")
            user = os.environ.get("PGUSER", "postgres")
            password = os.environ.get("PGPASSWORD", "")
            database = os.environ.get("PGDATABASE", "railway")
            url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
            # Railway Postgres always needs SSL
            connect_args = _ssl_connect_args()
        else:
            logger.warning(
                "No DATABASE_URL or PGHOST set — falling back to localhost. "
                "Set DATABASE_URL in Railway environment variables."
            )
            return "postgresql+asyncpg://user:password@localhost:5432/vans_uk", {}

    # Strip sslmode query param (asyncpg ignores it but logs warnings)
    # e.g. postgres://...?sslmode=require  →  postgresql+asyncpg://...
    url = re.sub(r"[?&]sslmode=[^&]*", "", url)
    url = re.sub(r"\?$", "", url)  # remove trailing ? if sslmode was the only param

    # Convert protocol prefix for asyncpg
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Add SSL for any non-localhost connection
    if _is_remote(url):
        connect_args = _ssl_connect_args()

    return url, connect_args


def _is_remote(url: str) -> bool:
    """True if the URL points to a remote host (not localhost/127.0.0.1)."""
    return "localhost" not in url and "127.0.0.1" not in url


def _ssl_connect_args() -> dict:
    """Return asyncpg-compatible SSL connect_args for Railway PostgreSQL."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Railway uses managed certs; skip verification
    return {"ssl": ctx}


DATABASE_URL, _CONNECT_ARGS = _build_database_url()

_ENGINE_CONNECT_ARGS = {**_CONNECT_ARGS, "timeout": 10}

engine = create_async_engine(
    DATABASE_URL,
    connect_args=_ENGINE_CONNECT_ARGS,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """
    Create all tables on startup.

    Logs a warning and continues if the DB is unreachable so the API
    still starts and the /health endpoint can respond.
    """
    # Log the host we're connecting to (never log the password)
    try:
        from urllib.parse import urlparse
        parsed = urlparse(DATABASE_URL)
        db_host = f"{parsed.hostname}:{parsed.port or 5432}/{parsed.path.lstrip('/')}"
    except Exception:
        db_host = "(unable to parse)"

    logger.info("Database host: %s", db_host)

    if "localhost" in DATABASE_URL and not os.environ.get("DATABASE_URL") and not os.environ.get("PGHOST"):
        logger.warning(
            "DATABASE_URL and PGHOST are not set — using localhost fallback. "
            "On Railway: add a Postgres plugin so DATABASE_URL is injected automatically."
        )

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialised at %s", db_host)
    except Exception as e:
        logger.warning(
            "Could not reach database at %s: %s — "
            "API will start but all DB endpoints will fail with 500. "
            "Fix: add a Postgres plugin in your Railway project.",
            db_host,
            type(e).__name__,
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
