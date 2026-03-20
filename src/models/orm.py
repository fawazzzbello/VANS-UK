# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""SQLAlchemy ORM models for VANS UK."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    ForeignKey,
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from src.models.database import Base

import enum


class ViolationType(str, enum.Enum):
    SPD = "SPD"  # Speeding
    RLR = "RLR"  # Red Light Running
    ILT = "ILT"  # Illegal Turn
    BUS = "BUS"  # Bus Lane Violation
    CON = "CON"  # Congestion Charge Evasion
    INS = "INS"  # No Insurance
    MOT = "MOT"  # No MOT
    TAX = "TAX"  # No Vehicle Tax
    PHN = "PHN"  # Phone Use While Driving
    SBT = "SBT"  # Seatbelt Violation


class Severity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertChannel(str, enum.Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"
    PUSH = "PUSH"
    WEBHOOK = "WEBHOOK"


class AlertStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


class TrafficEventORM(Base):
    __tablename__ = "traffic_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    road: Mapped[str | None] = mapped_column(String(100))
    observed_speed: Mapped[float | None] = mapped_column(Float)
    speed_limit: Mapped[int | None] = mapped_column(Integer)
    vehicle_plate: Mapped[str | None] = mapped_column(String(20), index=True)
    camera_id: Mapped[str | None] = mapped_column(String(100))
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_traffic_events_source_source_id", "source", "source_id", unique=True),
    )


class ViolationORM(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reference_number: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    violation_type: Mapped[str] = mapped_column(
        SAEnum(ViolationType, name="violation_type_enum"), nullable=False
    )
    severity: Mapped[str] = mapped_column(
        SAEnum(Severity, name="severity_enum"), nullable=False
    )
    vehicle_plate: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    vehicle_make: Mapped[str | None] = mapped_column(String(100))
    vehicle_model: Mapped[str | None] = mapped_column(String(100))
    vehicle_colour: Mapped[str | None] = mapped_column(String(50))
    registered_keeper_name: Mapped[str | None] = mapped_column(String(255))
    registered_keeper_phone: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    road: Mapped[str | None] = mapped_column(String(100))
    location_description: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    observed_speed: Mapped[float | None] = mapped_column(Float)
    speed_limit: Mapped[int | None] = mapped_column(Integer)
    camera_id: Mapped[str | None] = mapped_column(String(100))
    evidence_image_url: Mapped[str | None] = mapped_column(String(500))
    fine_amount_pence: Mapped[int | None] = mapped_column(Integer)
    points: Mapped[int | None] = mapped_column(Integer)
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    alerts: Mapped[list["AlertLogORM"]] = relationship(back_populates="violation")

    __table_args__ = (
        Index("ix_violations_type_timestamp", "violation_type", "timestamp"),
    )


class SubscriberORM(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    vehicle_plate: Mapped[str | None] = mapped_column(String(20), index=True)
    webhook_url: Mapped[str | None] = mapped_column(Text)
    alert_channels: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), default=["SMS"]
    )
    violation_types: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), default=["ALL"]
    )
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float, default=10.0)
    quiet_hours_start: Mapped[str | None] = mapped_column(String(5))
    quiet_hours_end: Mapped[str | None] = mapped_column(String(5))
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/London")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    alerts: Mapped[list["AlertLogORM"]] = relationship(back_populates="subscriber")


class AlertLogORM(Base):
    __tablename__ = "alert_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    violation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("violations.id"), nullable=False, index=True
    )
    subscriber_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("subscribers.id")
    )
    channel: Mapped[str] = mapped_column(
        SAEnum(AlertChannel, name="alert_channel_enum"), nullable=False
    )
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum(AlertStatus, name="alert_status_enum"),
        nullable=False,
        default=AlertStatus.PENDING,
    )
    message_sid: Mapped[str | None] = mapped_column(String(100))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    violation: Mapped["ViolationORM"] = relationship(back_populates="alerts")
    subscriber: Mapped["SubscriberORM | None"] = relationship(back_populates="alerts")


class SpeedLimitZoneORM(Base):
    __tablename__ = "speed_limit_zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    road: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_name: Mapped[str | None] = mapped_column(String(255))
    speed_limit_mph: Mapped[int] = mapped_column(Integer, nullable=False)
    latitude_start: Mapped[float] = mapped_column(Float, nullable=False)
    longitude_start: Mapped[float] = mapped_column(Float, nullable=False)
    latitude_end: Mapped[float] = mapped_column(Float, nullable=False)
    longitude_end: Mapped[float] = mapped_column(Float, nullable=False)
    is_variable: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class VehicleLookupCacheORM(Base):
    """Cache DVLA lookups to avoid repeated API calls."""

    __tablename__ = "vehicle_lookup_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_plate: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    make: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    colour: Mapped[str | None] = mapped_column(String(50))
    year: Mapped[int | None] = mapped_column(Integer)
    fuel_type: Mapped[str | None] = mapped_column(String(50))
    tax_status: Mapped[str | None] = mapped_column(String(50))
    tax_due_date: Mapped[str | None] = mapped_column(String(20))
    mot_status: Mapped[str | None] = mapped_column(String(50))
    mot_expiry_date: Mapped[str | None] = mapped_column(String(20))
    keeper_name: Mapped[str | None] = mapped_column(String(255))
    keeper_phone: Mapped[str | None] = mapped_column(String(20))
    keeper_address: Mapped[str | None] = mapped_column(Text)
    insurance_status: Mapped[str | None] = mapped_column(String(50))
    raw_response: Mapped[dict | None] = mapped_column(JSONB)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ANPRReadingORM(Base):
    """Raw ANPR camera readings before processing."""

    __tablename__ = "anpr_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    camera_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    camera_location: Mapped[str | None] = mapped_column(String(255))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    vehicle_plate: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    observed_speed_mph: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str | None] = mapped_column(String(20))
    lane: Mapped[int | None] = mapped_column(Integer)
    image_ref: Mapped[str | None] = mapped_column(String(500))
    road: Mapped[str | None] = mapped_column(String(100))
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_anpr_plate_timestamp", "vehicle_plate", "timestamp"),
    )
