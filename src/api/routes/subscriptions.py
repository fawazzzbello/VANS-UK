# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""Subscriber management endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from src.models.database import get_session
from src.models.orm import SubscriberORM
from src.models.schemas import SubscriberCreate, SubscriberResponse

router = APIRouter()


@router.post("/subscriptions", response_model=SubscriberResponse, status_code=201)
async def create_subscription(data: SubscriberCreate):
    """Register a new subscriber for violation alerts."""
    async with get_session() as session:
        subscriber = SubscriberORM(
            name=data.name,
            email=data.email,
            phone=data.phone,
            vehicle_plate=data.vehicle_plate,
            webhook_url=data.webhook_url,
            alert_channels=data.alert_channels,
            violation_types=data.violation_types,
            latitude=data.latitude,
            longitude=data.longitude,
            radius_km=data.radius_km,
        )
        session.add(subscriber)
        await session.flush()
        await session.refresh(subscriber)
        return SubscriberResponse.model_validate(subscriber)


@router.get("/subscriptions/{subscriber_id}", response_model=SubscriberResponse)
async def get_subscription(subscriber_id: int):
    """Get subscription details."""
    async with get_session() as session:
        result = await session.execute(
            select(SubscriberORM).where(SubscriberORM.id == subscriber_id)
        )
        subscriber = result.scalar_one_or_none()
        if not subscriber:
            raise HTTPException(status_code=404, detail="Subscriber not found")
        return SubscriberResponse.model_validate(subscriber)


@router.put("/subscriptions/{subscriber_id}", response_model=SubscriberResponse)
async def update_subscription(subscriber_id: int, data: SubscriberCreate):
    """Update subscriber preferences."""
    async with get_session() as session:
        result = await session.execute(
            select(SubscriberORM).where(SubscriberORM.id == subscriber_id)
        )
        subscriber = result.scalar_one_or_none()
        if not subscriber:
            raise HTTPException(status_code=404, detail="Subscriber not found")

        subscriber.name = data.name
        subscriber.email = data.email
        subscriber.phone = data.phone
        subscriber.vehicle_plate = data.vehicle_plate
        subscriber.webhook_url = data.webhook_url
        subscriber.alert_channels = data.alert_channels
        subscriber.violation_types = data.violation_types
        subscriber.latitude = data.latitude
        subscriber.longitude = data.longitude
        subscriber.radius_km = data.radius_km
        subscriber.updated_at = datetime.now(timezone.utc)

        await session.flush()
        await session.refresh(subscriber)
        return SubscriberResponse.model_validate(subscriber)


@router.delete("/subscriptions/{subscriber_id}", status_code=204)
async def delete_subscription(subscriber_id: int):
    """Deactivate a subscription."""
    async with get_session() as session:
        result = await session.execute(
            select(SubscriberORM).where(SubscriberORM.id == subscriber_id)
        )
        subscriber = result.scalar_one_or_none()
        if not subscriber:
            raise HTTPException(status_code=404, detail="Subscriber not found")
        subscriber.active = False
        subscriber.updated_at = datetime.now(timezone.utc)
