"""
Admin panel endpoints.

VRN Lookup   — full vehicle profile from DB + DVLA for any plate.
Test Suite   — fire a synthetic violation and verify SMS delivery end-to-end.
Camera Feed  — list ANPR cameras and stream recent readings per camera.
Footage      — retrieve evidence details for a specific violation.
"""

import logging
import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from src.alerting.notification_service import format_sms_message, get_sms_client
from src.ingestion.dvla_lookup import DVLALookupService
from src.models.database import get_session
from src.models.orm import AlertLogORM, ANPRReadingORM, ViolationORM
from src.models.schemas import AlertLogResponse, ViolationResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_dvla_service: DVLALookupService | None = None


def _get_dvla() -> DVLALookupService:
    global _dvla_service
    if _dvla_service is None:
        _dvla_service = DVLALookupService()
    return _dvla_service


# ── VRN Lookup ──────────────────────────────────────────────────────────────

@router.get("/admin/vrn/{plate}")
async def vrn_lookup(plate: str) -> dict:
    """
    Full vehicle profile for an admin VRN search.

    Returns:
      - DVLA vehicle info (make, model, colour, tax/MOT status)
      - All violations on record for this plate (most recent first)
      - Alert history tied to those violations
      - Summary totals (count, fines, outstanding amount)
    """
    plate = plate.upper().replace(" ", "").strip()
    if len(plate) < 2:
        raise HTTPException(status_code=400, detail="Invalid plate")

    async with get_session() as session:
        # DVLA lookup — uses 24h cache if available, live API otherwise
        owner = await _get_dvla().lookup_vehicle(plate, session)

        # All violations ever recorded for this plate
        violation_rows = (
            await session.execute(
                select(ViolationORM)
                .where(ViolationORM.vehicle_plate == plate)
                .order_by(ViolationORM.timestamp.desc())
                .limit(100)
            )
        ).scalars().all()

        # Alert log entries for those violations
        violation_ids = [v.id for v in violation_rows]
        alert_rows = []
        if violation_ids:
            alert_rows = (
                await session.execute(
                    select(AlertLogORM)
                    .where(AlertLogORM.violation_id.in_(violation_ids))
                    .order_by(AlertLogORM.created_at.desc())
                    .limit(100)
                )
            ).scalars().all()

        # Summary totals
        total_fines = sum(v.fine_amount_pence or 0 for v in violation_rows)
        outstanding = sum(
            v.fine_amount_pence or 0
            for v in violation_rows
            if v.status == "PENDING"
        )

        return {
            "vehicle_plate": plate,
            "dvla_info": {
                "make": owner.make,
                "model": owner.model,
                "colour": owner.colour,
                "year": owner.year,
                "fuel_type": owner.fuel_type,
                "tax_status": owner.tax_status,
                "tax_due_date": owner.tax_due_date,
                "mot_status": owner.mot_status,
                "mot_expiry_date": owner.mot_expiry_date,
                "insurance_status": owner.insurance_status,
                "keeper_name": owner.keeper_name,
            },
            "summary": {
                "total_violations": len(violation_rows),
                "total_fines_pence": total_fines,
                "outstanding_fines_pence": outstanding,
                "notifications_sent": sum(1 for v in violation_rows if v.notification_sent),
            },
            "violations": [
                ViolationResponse.model_validate(v).model_dump(mode="json")
                for v in violation_rows
            ],
            "alert_history": [
                AlertLogResponse.model_validate(a).model_dump(mode="json")
                for a in alert_rows
            ],
        }


# ── Test Alert Suite ─────────────────────────────────────────────────────────

_PENALTY = {
    "SPD": {"fine_pence": 10000, "points": 3},
    "RLR": {"fine_pence": 10000, "points": 3},
    "ILT": {"fine_pence": 10000, "points": 3},
    "BUS": {"fine_pence": 6500,  "points": 0},
    "CON": {"fine_pence": 16000, "points": 0},
    "INS": {"fine_pence": 30000, "points": 6},
    "MOT": {"fine_pence": 100000, "points": 0},
    "TAX": {"fine_pence": 100000, "points": 0},
    "PHN": {"fine_pence": 20000, "points": 6},
    "SBT": {"fine_pence": 50000, "points": 0},
}


def _test_description(vtype: str, road: str, speed: float, limit: int) -> str:
    return {
        "SPD": f"[TEST] Travelling at {speed:.0f}mph in a {limit}mph zone (+{speed - limit:.0f}mph over)",
        "RLR": f"[TEST] Red light running at controlled junction on {road}",
        "ILT": f"[TEST] Illegal turn at prohibited junction on {road}",
        "BUS": f"[TEST] Bus lane violation on {road}",
        "CON": f"[TEST] Congestion charge zone evasion on {road}",
        "INS": "[TEST] No valid insurance detected via DVLA",
        "MOT": "[TEST] MOT certificate expired or invalid",
        "TAX": "[TEST] Vehicle excise duty not paid",
        "PHN": "[TEST] Mobile phone use detected while driving",
        "SBT": "[TEST] Seatbelt not worn",
    }.get(vtype, f"[TEST] {vtype} violation on {road}")


class TestAlertRequest(BaseModel):
    vehicle_plate: str
    violation_type: str = "SPD"
    road: str = "M25"
    observed_speed: float = 85.0
    speed_limit: int = 70
    # Phone to receive the test SMS.
    # Falls back to TEST_SMS_RECIPIENT env var if not provided.
    test_phone: str | None = None


@router.post("/admin/test/alert")
async def test_alert(body: TestAlertRequest) -> dict:
    """
    Fire a synthetic violation and send a real SMS to a test number.

    The violation is NOT written to the database — this purely exercises the
    Twilio SMS path so an admin can confirm the alert pipeline is wired up.

    Requires either:
      - body.test_phone set in the request, OR
      - TEST_SMS_RECIPIENT environment variable configured
    """
    test_phone = body.test_phone or os.environ.get("TEST_SMS_RECIPIENT", "")
    if not test_phone:
        raise HTTPException(
            status_code=400,
            detail=(
                "No test phone number provided. "
                "Pass test_phone in the request body "
                "or set the TEST_SMS_RECIPIENT environment variable."
            ),
        )

    plate = body.vehicle_plate.upper().replace(" ", "").strip()
    if len(plate) < 2:
        raise HTTPException(status_code=400, detail="Invalid plate")

    vtype = body.violation_type.upper()
    if vtype not in _PENALTY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown violation type '{vtype}'. Valid: {', '.join(_PENALTY)}",
        )

    penalty = _PENALTY[vtype]
    ref = f"TEST-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}"

    violation_data = {
        "violation_id": None,
        "reference_number": ref,
        "violation_type": vtype,
        "severity": "HIGH",
        "vehicle_plate": plate,
        "keeper_name": "Test Recipient",
        "keeper_phone": test_phone,
        "road": body.road,
        "description": _test_description(vtype, body.road, body.observed_speed, body.speed_limit),
        "fine_amount_pence": penalty["fine_pence"],
        "points": penalty["points"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "processing_time_ms": 0,
    }

    sms_message = format_sms_message(violation_data)

    t0 = time.monotonic()
    result = await get_sms_client().send_sms(test_phone, sms_message)
    latency_ms = int((time.monotonic() - t0) * 1000)

    if result["success"]:
        logger.info("Test SMS sent to %s for plate %s ref %s", test_phone, plate, ref)
    else:
        logger.warning("Test SMS failed to %s: %s", test_phone, result.get("error"))

    return {
        "test_reference": ref,
        "vehicle_plate": plate,
        "violation_type": vtype,
        "test_phone": test_phone,
        "sms_sent": result["success"],
        "sms_message": sms_message,
        "latency_ms": latency_ms,
        "twilio_sid": result.get("message_sid"),
        "error": result.get("error"),
        "note": "Test only — no database record created",
    }


# ── Camera Monitoring ─────────────────────────────────────────────────────────

@router.get("/admin/cameras")
async def list_cameras() -> dict:
    """
    List all ANPR cameras seen in the database with their latest reading.

    Returns one entry per camera_id with:
      - location, coordinates
      - last plate read and timestamp
      - last observed speed
      - total reading count
      - status: ACTIVE (reading in last 5 min) | IDLE (last hour) | OFFLINE
    """
    async with get_session() as session:
        # Get all distinct camera IDs with their most recent reading
        subq = (
            select(
                ANPRReadingORM.camera_id,
                func.max(ANPRReadingORM.timestamp).label("last_seen"),
            )
            .group_by(ANPRReadingORM.camera_id)
            .subquery()
        )

        rows = (
            await session.execute(
                select(ANPRReadingORM, subq.c.last_seen)
                .join(
                    subq,
                    (ANPRReadingORM.camera_id == subq.c.camera_id)
                    & (ANPRReadingORM.timestamp == subq.c.last_seen),
                )
                .order_by(subq.c.last_seen.desc())
            )
        ).all()

        # Count readings per camera
        count_rows = (
            await session.execute(
                select(
                    ANPRReadingORM.camera_id,
                    func.count(ANPRReadingORM.id).label("total"),
                ).group_by(ANPRReadingORM.camera_id)
            )
        ).all()
        counts = {r.camera_id: r.total for r in count_rows}

        now = datetime.now(timezone.utc)
        cameras = []
        for reading, last_seen in rows:
            age_seconds = (now - last_seen.replace(tzinfo=timezone.utc) if last_seen.tzinfo is None else now - last_seen).total_seconds()
            if age_seconds < 300:
                status = "ACTIVE"
            elif age_seconds < 3600:
                status = "IDLE"
            else:
                status = "OFFLINE"

            cameras.append({
                "camera_id": reading.camera_id,
                "location": reading.camera_location or reading.road or "Unknown",
                "road": reading.road,
                "latitude": reading.latitude,
                "longitude": reading.longitude,
                "last_plate": reading.vehicle_plate,
                "last_speed_mph": reading.observed_speed_mph,
                "last_seen": last_seen.isoformat() if last_seen else None,
                "total_readings": counts.get(reading.camera_id, 0),
                "status": status,
            })

        return {
            "cameras": cameras,
            "total": len(cameras),
            "timestamp": now.isoformat(),
        }


@router.get("/admin/cameras/{camera_id}/feed")
async def camera_feed(camera_id: str, limit: int = 20) -> dict:
    """
    Recent ANPR readings from a specific camera (most recent first).
    Used to simulate a live camera feed in the admin dashboard.
    """
    if limit > 100:
        limit = 100

    async with get_session() as session:
        readings = (
            await session.execute(
                select(ANPRReadingORM)
                .where(ANPRReadingORM.camera_id == camera_id)
                .order_by(ANPRReadingORM.timestamp.desc())
                .limit(limit)
            )
        ).scalars().all()

        if not readings:
            raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found")

        latest = readings[0]
        return {
            "camera_id": camera_id,
            "location": latest.camera_location or latest.road or "Unknown",
            "latitude": latest.latitude,
            "longitude": latest.longitude,
            "readings": [
                {
                    "id": r.id,
                    "vehicle_plate": r.vehicle_plate,
                    "observed_speed_mph": r.observed_speed_mph,
                    "confidence": r.confidence,
                    "direction": r.direction,
                    "lane": r.lane,
                    "image_ref": r.image_ref,
                    "processed": r.processed,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in readings
            ],
            "count": len(readings),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ── Violation Evidence ────────────────────────────────────────────────────────

@router.get("/admin/footage/{violation_ref}")
async def violation_footage(violation_ref: str) -> dict:
    """
    Retrieve evidence details for a violation by reference number or numeric ID.

    Returns:
      - Full violation record
      - Evidence image URL (if captured by ANPR camera)
      - Related ANPR readings from the same camera around the time of the violation
      - Alert history for this violation
    """
    async with get_session() as session:
        # Allow lookup by reference number (e.g. VUK-...) or numeric id
        if violation_ref.isdigit():
            row = (
                await session.execute(
                    select(ViolationORM).where(ViolationORM.id == int(violation_ref))
                )
            ).scalar_one_or_none()
        else:
            row = (
                await session.execute(
                    select(ViolationORM).where(
                        ViolationORM.reference_number == violation_ref.upper()
                    )
                )
            ).scalar_one_or_none()

        if not row:
            raise HTTPException(status_code=404, detail="Violation not found")

        # Related ANPR readings: same camera ±60 s of the violation
        related_readings = []
        if row.camera_id:
            from datetime import timedelta
            ts = row.timestamp
            related_readings = (
                await session.execute(
                    select(ANPRReadingORM)
                    .where(
                        ANPRReadingORM.camera_id == row.camera_id,
                        ANPRReadingORM.timestamp >= ts - timedelta(seconds=60),
                        ANPRReadingORM.timestamp <= ts + timedelta(seconds=60),
                    )
                    .order_by(ANPRReadingORM.timestamp)
                    .limit(10)
                )
            ).scalars().all()

        # Alert history
        alerts = (
            await session.execute(
                select(AlertLogORM)
                .where(AlertLogORM.violation_id == row.id)
                .order_by(AlertLogORM.created_at)
            )
        ).scalars().all()

        return {
            "violation": ViolationResponse.model_validate(row).model_dump(mode="json"),
            "evidence": {
                "image_url": row.evidence_image_url,
                "camera_id": row.camera_id,
                "has_image": bool(row.evidence_image_url),
            },
            "related_anpr_readings": [
                {
                    "id": r.id,
                    "vehicle_plate": r.vehicle_plate,
                    "observed_speed_mph": r.observed_speed_mph,
                    "confidence": r.confidence,
                    "image_ref": r.image_ref,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in related_readings
            ],
            "alert_history": [
                AlertLogResponse.model_validate(a).model_dump(mode="json")
                for a in alerts
            ],
        }
