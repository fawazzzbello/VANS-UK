"""Violation CRUD and statistics endpoints."""

import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, and_

from src.models.database import get_session
from src.models.orm import ViolationORM, AlertLogORM
from src.models.schemas import ViolationResponse, ViolationStats, PaginatedResponse

router = APIRouter()


@router.get("/violations", response_model=PaginatedResponse)
async def list_violations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    violation_type: str | None = None,
    severity: str | None = None,
    vehicle_plate: str | None = None,
    road: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    """
    Query violations with filtering and pagination.

    Supports filtering by type, severity, plate, road, status, and date range.
    """
    async with get_session() as session:
        query = select(ViolationORM)
        count_query = select(func.count(ViolationORM.id))

        # Apply filters
        conditions = []
        if violation_type:
            conditions.append(ViolationORM.violation_type == violation_type)
        if severity:
            conditions.append(ViolationORM.severity == severity)
        if vehicle_plate:
            plate = vehicle_plate.upper().replace(" ", "")
            conditions.append(ViolationORM.vehicle_plate == plate)
        if road:
            conditions.append(ViolationORM.road == road)
        if status:
            conditions.append(ViolationORM.status == status)
        if date_from:
            conditions.append(ViolationORM.timestamp >= date_from)
        if date_to:
            conditions.append(ViolationORM.timestamp <= date_to)

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        # Get total count
        total = (await session.execute(count_query)).scalar() or 0
        total_pages = math.ceil(total / page_size) if total > 0 else 0

        # Get page
        offset = (page - 1) * page_size
        query = query.order_by(ViolationORM.timestamp.desc())
        query = query.offset(offset).limit(page_size)
        result = await session.execute(query)
        violations = result.scalars().all()

        items = [
            ViolationResponse.model_validate(v).model_dump()
            for v in violations
        ]

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


@router.get("/violations/stats", response_model=ViolationStats)
async def get_violation_stats():
    """Aggregated violation statistics for dashboards."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    async with get_session() as session:
        total = (
            await session.execute(select(func.count(ViolationORM.id)))
        ).scalar() or 0

        today = (
            await session.execute(
                select(func.count(ViolationORM.id)).where(
                    ViolationORM.timestamp >= today_start
                )
            )
        ).scalar() or 0

        this_week = (
            await session.execute(
                select(func.count(ViolationORM.id)).where(
                    ViolationORM.timestamp >= week_start
                )
            )
        ).scalar() or 0

        this_month = (
            await session.execute(
                select(func.count(ViolationORM.id)).where(
                    ViolationORM.timestamp >= month_start
                )
            )
        ).scalar() or 0

        # By type
        type_results = await session.execute(
            select(
                ViolationORM.violation_type,
                func.count(ViolationORM.id),
            ).group_by(ViolationORM.violation_type)
        )
        by_type = {row[0]: row[1] for row in type_results}

        # By severity
        sev_results = await session.execute(
            select(
                ViolationORM.severity,
                func.count(ViolationORM.id),
            ).group_by(ViolationORM.severity)
        )
        by_severity = {row[0]: row[1] for row in sev_results}

        # Top roads
        road_results = await session.execute(
            select(
                ViolationORM.road,
                func.count(ViolationORM.id).label("count"),
            )
            .where(ViolationORM.road.isnot(None))
            .group_by(ViolationORM.road)
            .order_by(func.count(ViolationORM.id).desc())
            .limit(10)
        )
        by_road = [{"road": row[0], "count": row[1]} for row in road_results]

        # Notification latency
        latency_result = await session.execute(
            select(func.avg(AlertLogORM.latency_ms)).where(
                AlertLogORM.latency_ms.isnot(None)
            )
        )
        avg_latency = latency_result.scalar()

        # Notification success rate
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
        success_rate = (
            (sent_alerts / total_alerts * 100) if total_alerts > 0 else None
        )

        return ViolationStats(
            total_violations=total,
            violations_today=today,
            violations_this_week=this_week,
            violations_this_month=this_month,
            by_type=by_type,
            by_severity=by_severity,
            by_road=by_road,
            avg_notification_latency_ms=avg_latency,
            notification_success_rate=success_rate,
        )


@router.get("/violations/{violation_id}", response_model=ViolationResponse)
async def get_violation(violation_id: int):
    """Get a single violation by ID."""
    async with get_session() as session:
        result = await session.execute(
            select(ViolationORM).where(ViolationORM.id == violation_id)
        )
        violation = result.scalar_one_or_none()
        if not violation:
            raise HTTPException(status_code=404, detail="Violation not found")
        return ViolationResponse.model_validate(violation)


@router.get("/violations/ref/{reference_number}", response_model=ViolationResponse)
async def get_violation_by_ref(reference_number: str):
    """Get a violation by its reference number (e.g. VN-20260313-A1B2C)."""
    async with get_session() as session:
        result = await session.execute(
            select(ViolationORM).where(
                ViolationORM.reference_number == reference_number
            )
        )
        violation = result.scalar_one_or_none()
        if not violation:
            raise HTTPException(status_code=404, detail="Violation not found")
        return ViolationResponse.model_validate(violation)
