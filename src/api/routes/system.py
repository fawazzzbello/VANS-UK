"""System routes: health, readiness, metrics."""

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import func, select, text

from src.models.database import get_session
from src.models.orm import ViolationORM, AlertLogORM

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
    """Readiness check - verifies database connectivity."""
    checks = {}

    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
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
