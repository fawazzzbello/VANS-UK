"""System routes: health, readiness, metrics."""

import os
from datetime import datetime, timezone

import redis.asyncio as redis
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic liveness check."""
    return {
        "status": "healthy",
        "service": "vans-uk",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready")
async def readiness_check():
    """Readiness check - verifies database and Redis connectivity."""
    checks = {}

    # Check Redis
    try:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        r = redis.from_url(redis_url)
        await r.ping()
        checks["redis"] = "ok"
        await r.aclose()
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Check Database
    try:
        from src.models.database import get_session
        async with get_session() as session:
            await session.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "ready": all_ok,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/v1/metrics")
async def get_metrics():
    """System metrics for monitoring dashboards."""
    try:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        r = redis.from_url(redis_url)
        stream_info = {}
        for stream in ["anpr_readings_raw", "anpr_readings", "violations", "notifications"]:
            try:
                info = await r.xinfo_stream(stream)
                stream_info[stream] = {
                    "length": info.get("length", 0),
                    "groups": info.get("groups", 0),
                }
            except redis.ResponseError:
                stream_info[stream] = {"length": 0, "groups": 0}
        await r.aclose()
    except Exception:
        stream_info = {}

    return {
        "streams": stream_info,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
