# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""ANPR endpoints - submit readings, run simulations, full in-process pipeline."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.ingestion.anpr_processor import normalize_reading, generate_reading
from src.processing.violation_engine import process_reading
from src.alerting.notification_service import send_violation_notification

logger = logging.getLogger(__name__)
router = APIRouter()


class ANPRReading(BaseModel):
    """Schema for submitting an ANPR camera reading."""

    camera_id: str
    camera_location: str | None = None
    vehicle_plate: str = Field(min_length=2, max_length=20)
    confidence: float = Field(ge=0, le=1)
    observed_speed_mph: float | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    direction: str | None = None
    lane: int | None = None
    road: str | None = None
    speed_limit: int | None = None
    image_ref: str | None = None
    timestamp: str | None = None


class SimulationRequest(BaseModel):
    readings_per_second: int = Field(10, ge=1, le=1000)
    duration_seconds: int = Field(60, ge=1, le=3600)


async def _process_and_notify(raw: dict[str, Any]) -> dict[str, Any]:
    """Full pipeline: normalize → detect violations → send notifications."""
    normalized = normalize_reading(raw)
    if normalized is None:
        return {"status": "skipped", "reason": "low_confidence_or_invalid_plate"}

    violations = await process_reading(normalized)

    notifications_sent = 0
    for v in violations:
        try:
            result = await send_violation_notification(v)
            if result.get("sms_sent"):
                notifications_sent += 1
        except Exception:
            logger.exception("Notification failed for %s", v.get("reference_number"))

    return {
        "status": "processed",
        "plate": normalized["vehicle_plate"],
        "violations_detected": len(violations),
        "notifications_sent": notifications_sent,
        "violations": [
            {
                "reference_number": v["reference_number"],
                "type": v["violation_type"],
                "severity": v["severity"],
                "fine_pence": v["fine_amount_pence"],
                "points": v["points"],
            }
            for v in violations
        ],
    }


@router.post("/anpr/readings")
async def submit_anpr_reading(reading: ANPRReading):
    """
    Submit a single ANPR camera reading.

    Full in-process pipeline: normalize → violation detection → instant SMS.
    Returns violation details immediately.
    """
    try:
        result = await _process_and_notify(reading.model_dump())
        return result
    except Exception:
        logger.exception("Failed to process ANPR reading")
        raise HTTPException(status_code=500, detail="Processing failed")


@router.post("/anpr/readings/batch")
async def submit_anpr_batch(readings: list[ANPRReading]):
    """Submit a batch of ANPR readings. Each is processed through the full pipeline."""
    if len(readings) > 1000:
        raise HTTPException(
            status_code=400, detail="Maximum 1000 readings per batch"
        )

    results = []
    for reading in readings:
        try:
            result = await _process_and_notify(reading.model_dump())
            results.append(result)
        except Exception:
            logger.exception("Failed to process reading for %s", reading.vehicle_plate)
            results.append({"status": "error", "plate": reading.vehicle_plate})

    total_violations = sum(r.get("violations_detected", 0) for r in results)
    total_notifications = sum(r.get("notifications_sent", 0) for r in results)

    return {
        "status": "completed",
        "total_readings": len(readings),
        "total_violations": total_violations,
        "total_notifications": total_notifications,
        "results": results,
    }


@router.post("/anpr/simulate")
async def start_simulation(req: SimulationRequest):
    """
    Start an ANPR simulation for testing and demonstration.

    Generates realistic UK number plates and speed readings,
    processes each through the full violation detection pipeline.
    """
    async def _run_simulation():
        processed = 0
        violations_found = 0
        for _ in range(req.duration_seconds):
            for _ in range(req.readings_per_second):
                raw = generate_reading()
                try:
                    result = await _process_and_notify(raw)
                    processed += 1
                    violations_found += result.get("violations_detected", 0)
                except Exception:
                    logger.exception("Simulation reading failed")
            await asyncio.sleep(1)
        logger.info(
            "Simulation complete: %d readings, %d violations",
            processed, violations_found,
        )

    asyncio.create_task(_run_simulation())

    return {
        "status": "simulation_started",
        "readings_per_second": req.readings_per_second,
        "duration_seconds": req.duration_seconds,
        "total_expected": req.readings_per_second * req.duration_seconds,
    }
