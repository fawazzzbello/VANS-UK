"""Traffic data endpoints - incidents, flow, roadworks."""

import math
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func, select, and_

from src.models.database import get_session
from src.models.orm import TrafficEventORM
from src.models.schemas import PaginatedResponse, TrafficEventResponse

router = APIRouter()


@router.get("/traffic/incidents", response_model=PaginatedResponse)
async def list_incidents(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    source: str | None = None,
    severity: str | None = None,
    road: str | None = None,
):
    """Get current traffic incidents with optional filtering."""
    async with get_session() as session:
        query = select(TrafficEventORM)
        count_query = select(func.count(TrafficEventORM.id))

        conditions = []
        if source:
            conditions.append(TrafficEventORM.source == source)
        if severity:
            conditions.append(TrafficEventORM.severity == severity)
        if road:
            conditions.append(TrafficEventORM.road == road)

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total = (await session.execute(count_query)).scalar() or 0
        total_pages = math.ceil(total / page_size) if total > 0 else 0

        offset = (page - 1) * page_size
        query = query.order_by(TrafficEventORM.timestamp.desc())
        query = query.offset(offset).limit(page_size)
        result = await session.execute(query)
        events = result.scalars().all()

        items = [
            TrafficEventResponse.model_validate(e).model_dump()
            for e in events
        ]

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


@router.get("/traffic/roadworks", response_model=PaginatedResponse)
async def list_roadworks(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    road: str | None = None,
):
    """Get active roadworks."""
    async with get_session() as session:
        query = select(TrafficEventORM).where(
            TrafficEventORM.event_type == "ROADWORKS"
        )
        count_query = select(func.count(TrafficEventORM.id)).where(
            TrafficEventORM.event_type == "ROADWORKS"
        )

        if road:
            query = query.where(TrafficEventORM.road == road)
            count_query = count_query.where(TrafficEventORM.road == road)

        total = (await session.execute(count_query)).scalar() or 0
        total_pages = math.ceil(total / page_size) if total > 0 else 0

        offset = (page - 1) * page_size
        query = query.order_by(TrafficEventORM.timestamp.desc())
        query = query.offset(offset).limit(page_size)
        result = await session.execute(query)
        events = result.scalars().all()

        items = [
            TrafficEventResponse.model_validate(e).model_dump()
            for e in events
        ]

        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
