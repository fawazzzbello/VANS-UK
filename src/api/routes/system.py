"""System routes: health, readiness, metrics."""

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text

from src.models.database import get_session, DATABASE_URL
from src.models.orm import ViolationORM, AlertLogORM

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic liveness check — always 200 if the process is running."""
    return {
        "status": "healthy",
        "service": "vans-uk",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready")
async def readiness_check():
    """
    Readiness check — returns 200 only when the database is reachable.
    Returns 503 otherwise so load balancers and Railway stop routing traffic.
    """
    db_ok = False
    db_error = None

    # Show only the host portion of the URL for diagnostics (never the password)
    try:
        from urllib.parse import urlparse
        parsed = urlparse(DATABASE_URL)
        db_host = f"{parsed.hostname}:{parsed.port or 5432}"
    except Exception:
        db_host = "unknown"

    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_error = str(e)[:200]  # truncate very long asyncpg traces

    payload = {
        "ready": db_ok,
        "checks": {
            "database": "ok" if db_ok else f"error — {db_error}",
        },
        "db_host": db_host,
        "hint": (
            None if db_ok else
            "DATABASE_URL is not set or the PostgreSQL service is unreachable. "
            "Add a Postgres plugin in your Railway project and redeploy."
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    status_code = 200 if db_ok else 503
    return JSONResponse(content=payload, status_code=status_code)


@router.get("/api/v1/metrics")
async def get_metrics():
    """System metrics for monitoring dashboards."""
    metrics = {}

    try:
        async with get_session() as session:
            total_violations = (
                await session.execute(select(func.count(ViolationORM.id)))
            ).scalar() or 0

            pending_violations = (
                await session.execute(
                    select(func.count(ViolationORM.id)).where(
                        ViolationORM.status == "PENDING"
                    )
                )
            ).scalar() or 0

            total_alerts = (
                await session.execute(select(func.count(AlertLogORM.id)))
            ).scalar() or 0

            sent_alerts = (
                await session.execute(
                    select(func.count(AlertLogORM.id)).where(
                        AlertLogORM.status == "SENT"
                    )
                )
            ).scalar() or 0

            avg_latency = (
                await session.execute(
                    select(func.avg(AlertLogORM.latency_ms)).where(
                        AlertLogORM.latency_ms.isnot(None)
                    )
                )
            ).scalar()

            metrics = {
                "violations": {
                    "total": total_violations,
                    "pending": pending_violations,
                },
                "alerts": {
                    "total": total_alerts,
                    "sent": sent_alerts,
                    "success_rate": round(sent_alerts / total_alerts * 100, 1) if total_alerts > 0 else None,
                    "avg_latency_ms": round(avg_latency, 1) if avg_latency else None,
                },
            }
    except Exception:
        metrics = {"error": "Database unavailable"}

    metrics["timestamp"] = datetime.now(timezone.utc).isoformat()
    return metrics


@router.get("/api/v1/metrics")
async def get_metrics():
    """System metrics for monitoring dashboards."""
    metrics = {}

    try:
        async with get_session() as session:
            # Violation counts
            total_violations = (
                await session.execute(select(func.count(ViolationORM.id)))
            ).scalar() or 0

            pending_violations = (
                await session.execute(
                    select(func.count(ViolationORM.id)).where(
                        ViolationORM.status == "PENDING"
                    )
                )
            ).scalar() or 0

            # Alert stats
            total_alerts = (
                await session.execute(select(func.count(AlertLogORM.id)))
            ).scalar() or 0

            sent_alerts = (
                await session.execute(
                    select(func.count(AlertLogORM.id)).where(
                        AlertLogORM.status == "SENT"
                    )
                )
            ).scalar() or 0

            avg_latency = (
                await session.execute(
                    select(func.avg(AlertLogORM.latency_ms)).where(
                        AlertLogORM.latency_ms.isnot(None)
                    )
                )
            ).scalar()

            metrics = {
                "violations": {
                    "total": total_violations,
                    "pending": pending_violations,
                },
                "alerts": {
                    "total": total_alerts,
                    "sent": sent_alerts,
                    "success_rate": round(sent_alerts / total_alerts * 100, 1) if total_alerts > 0 else None,
                    "avg_latency_ms": round(avg_latency, 1) if avg_latency else None,
                },
            }
    except Exception:
        metrics = {"error": "Database unavailable"}

    metrics["timestamp"] = datetime.now(timezone.utc).isoformat()
    return metrics
