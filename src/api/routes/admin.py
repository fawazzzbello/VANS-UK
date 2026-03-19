"""
Admin panel endpoints.

VRN Lookup — full vehicle profile from DB + DVLA for any plate.
Test Suite  — fire a synthetic violation and verify SMS delivery end-to-end.
"""

import logging
import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from src.alerting.notification_service import format_sms_message, get_sms_client
from src.ingestion.dvla_lookup import DVLALookupService
from src.models.database import get_session
from src.models.orm import AlertLogORM, ViolationORM
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
