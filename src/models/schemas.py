# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TrafficEventCreate(BaseModel):
    source: str
    source_id: str
    event_type: str
    severity: str
    description: str | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    road: str | None = None
    observed_speed: float | None = None
    speed_limit: int | None = None
    vehicle_plate: str | None = None
    camera_id: str | None = None
    timestamp: datetime


class TrafficEventResponse(BaseModel):
    id: int
    source: str
    source_id: str
    event_type: str
    severity: str
    description: str | None
    latitude: float
    longitude: float
    road: str | None
    timestamp: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class ViolationCreate(BaseModel):
    violation_type: str
    severity: str
    vehicle_plate: str = Field(min_length=2, max_length=20)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    road: str | None = None
    location_description: str | None = None
    description: str | None = None
    observed_speed: float | None = None
    speed_limit: int | None = None
    camera_id: str | None = None
    evidence_image_url: str | None = None
    timestamp: datetime

    @field_validator("vehicle_plate")
    @classmethod
    def normalize_plate(cls, v: str) -> str:
        return v.upper().replace(" ", "").strip()


class ViolationResponse(BaseModel):
    id: int
    reference_number: str
    violation_type: str
    severity: str
    vehicle_plate: str
    vehicle_make: str | None
    vehicle_model: str | None
    vehicle_colour: str | None
    latitude: float
    longitude: float
    road: str | None
    location_description: str | None
    description: str | None
    observed_speed: float | None
    speed_limit: int | None
    fine_amount_pence: int | None
    points: int | None
    notification_sent: bool
    notification_sent_at: datetime | None
    status: str
    timestamp: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class ViolationStats(BaseModel):
    total_violations: int
    violations_today: int
    violations_this_week: int
    violations_this_month: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    by_road: list[dict[str, Any]]
    avg_notification_latency_ms: float | None
    notification_success_rate: float | None


class VehicleOwner(BaseModel):
    """Vehicle owner information from DVLA lookup."""

    vehicle_plate: str
    make: str | None = None
    model: str | None = None
    colour: str | None = None
    year: int | None = None
    fuel_type: str | None = None
    tax_status: str | None = None
    tax_due_date: str | None = None
    mot_status: str | None = None
    mot_expiry_date: str | None = None
    keeper_name: str | None = None
    keeper_phone: str | None = None
    insurance_status: str | None = None


class SubscriberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str | None = None
    phone: str | None = None
    vehicle_plate: str | None = None
    webhook_url: str | None = None
    alert_channels: list[str] = ["SMS"]
    violation_types: list[str] = ["ALL"]
    latitude: float | None = None
    longitude: float | None = None
    radius_km: float = 10.0

    @field_validator("vehicle_plate")
    @classmethod
    def normalize_plate(cls, v: str | None) -> str | None:
        if v is not None:
            return v.upper().replace(" ", "").strip()
        return v


class SubscriberResponse(BaseModel):
    id: int
    name: str
    email: str | None
    phone: str | None
    vehicle_plate: str | None
    alert_channels: list[str] | None
    violation_types: list[str] | None
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertLogResponse(BaseModel):
    id: int
    violation_id: int
    channel: str
    recipient: str
    status: str
    latency_ms: int | None
    sent_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
