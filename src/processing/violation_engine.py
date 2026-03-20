# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""
Real-Time Violation Detection Engine.

Processes ANPR readings directly (in-process, no Redis required):
1. Validates and normalizes the reading
2. Checks for speeding violations
3. Looks up vehicle owner via DVLA
4. Checks tax/MOT/insurance status
5. Creates violation records in PostgreSQL
6. Returns violations for immediate notification

Target latency: ANPR read -> violation detected in under 5 seconds.
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from src.ingestion.dvla_lookup import DVLALookupService
from src.models.database import get_session
from src.models.orm import ViolationORM, ViolationType, Severity

logger = logging.getLogger(__name__)

# Speed tolerance before a violation is raised (mph)
SPEED_TOLERANCE_MPH = 2

# Fines and points per violation type (UK penalty system)
PENALTY_SCHEDULE = {
    ViolationType.SPD: {"fine_pence": 10000, "points": 3},  # £100, 3 points
    ViolationType.RLR: {"fine_pence": 10000, "points": 3},  # £100, 3 points
    ViolationType.ILT: {"fine_pence": 10000, "points": 3},  # £100, 3 points
    ViolationType.BUS: {"fine_pence": 6500, "points": 0},   # £65, 0 points
    ViolationType.CON: {"fine_pence": 16000, "points": 0},  # £160, 0 points
    ViolationType.INS: {"fine_pence": 30000, "points": 6},  # £300, 6 points
    ViolationType.MOT: {"fine_pence": 100000, "points": 0}, # £1000, 0 points
    ViolationType.TAX: {"fine_pence": 100000, "points": 0}, # £1000, 0 points
    ViolationType.PHN: {"fine_pence": 20000, "points": 6},  # £200, 6 points
    ViolationType.SBT: {"fine_pence": 50000, "points": 0},  # £500, 0 points
}

# Shared DVLA service instance (created on first use)
_dvla_service: DVLALookupService | None = None


def get_dvla_service() -> DVLALookupService:
    global _dvla_service
    if _dvla_service is None:
        _dvla_service = DVLALookupService()
    return _dvla_service


def generate_reference_number() -> str:
    """Generate a unique violation reference number. Format: VN-YYYYMMDD-XXXXX."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    unique_part = uuid.uuid4().hex[:5].upper()
    return f"VN-{date_part}-{unique_part}"


def classify_speed_severity(amount_over: float) -> Severity:
    """Classify speeding severity based on mph over limit."""
    if amount_over >= 20:
        return Severity.CRITICAL
    elif amount_over >= 10:
        return Severity.HIGH
    elif amount_over >= 5:
        return Severity.MEDIUM
    return Severity.LOW


async def process_reading(data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Process a single ANPR reading. Detects all violation types,
    creates DB records, and returns violation data for notification.

    This is the core pipeline function called directly from the API.
    No Redis required.

    Returns list of violation dicts (empty if no violations found).
    """
    start_time = time.monotonic()

    plate = str(data.get("vehicle_plate", "")).upper().replace(" ", "").strip()
    if not plate or len(plate) < 2:
        return []

    observed_speed = data.get("observed_speed_mph") or data.get("observed_speed")
    speed_limit_val = data.get("speed_limit")
    lat = float(data.get("latitude", 0))
    lon = float(data.get("longitude", 0))
    road = str(data.get("road", ""))
    camera_id = str(data.get("camera_id", ""))
    camera_location = str(data.get("camera_location", ""))
    image_ref = str(data.get("image_ref", ""))
    timestamp_str = data.get("timestamp", "")

    try:
        timestamp = datetime.fromisoformat(str(timestamp_str))
    except (ValueError, TypeError):
        timestamp = datetime.now(timezone.utc)

    violations_found: list[dict[str, Any]] = []

    # 1. Check for speeding violation
    if observed_speed is not None and speed_limit_val is not None:
        speed = float(observed_speed)
        limit = int(float(speed_limit_val))
        if speed > limit + SPEED_TOLERANCE_MPH:
            amount_over = speed - limit
            violations_found.append({
                "type": ViolationType.SPD,
                "severity": classify_speed_severity(amount_over),
                "description": (
                    f"Travelling at {speed:.0f}mph in a {limit}mph zone "
                    f"(+{amount_over:.0f}mph over limit)"
                ),
                "observed_speed": speed,
                "speed_limit": limit,
            })

    # 2. Check DVLA for tax/MOT/insurance status
    dvla = get_dvla_service()
    created_violations = []

    async with get_session() as session:
        owner = await dvla.lookup_vehicle(plate, session)

        if owner.tax_status and owner.tax_status not in ("Taxed", "SORN"):
            violations_found.append({
                "type": ViolationType.TAX,
                "severity": Severity.HIGH,
                "description": f"Vehicle tax status: {owner.tax_status}",
            })

        if owner.mot_status == "Not valid":
            violations_found.append({
                "type": ViolationType.MOT,
                "severity": Severity.HIGH,
                "description": (
                    f"MOT status: {owner.mot_status}. "
                    f"Expired: {owner.mot_expiry_date or 'unknown'}"
                ),
            })

        if owner.insurance_status and owner.insurance_status != "Insured":
            violations_found.append({
                "type": ViolationType.INS,
                "severity": Severity.CRITICAL,
                "description": f"No valid insurance. Status: {owner.insurance_status}",
            })

        # 3. Create violation records in PostgreSQL
        for v in violations_found:
            penalty = PENALTY_SCHEDULE.get(v["type"], {"fine_pence": 0, "points": 0})
            ref_number = generate_reference_number()

            violation = ViolationORM(
                reference_number=ref_number,
                violation_type=v["type"].value,
                severity=v["severity"].value,
                vehicle_plate=plate,
                vehicle_make=owner.make,
                vehicle_model=owner.model,
                vehicle_colour=owner.colour,
                registered_keeper_name=owner.keeper_name,
                registered_keeper_phone=owner.keeper_phone,
                latitude=lat,
                longitude=lon,
                road=road,
                location_description=camera_location,
                description=v["description"],
                observed_speed=v.get("observed_speed"),
                speed_limit=v.get("speed_limit"),
                camera_id=camera_id,
                evidence_image_url=image_ref,
                fine_amount_pence=penalty["fine_pence"],
                points=penalty["points"],
                status="PENDING",
                timestamp=timestamp,
            )
            session.add(violation)
            await session.flush()

            processing_time_ms = int((time.monotonic() - start_time) * 1000)

            violation_data = {
                "violation_id": violation.id,
                "reference_number": ref_number,
                "violation_type": v["type"].value,
                "severity": v["severity"].value,
                "vehicle_plate": plate,
                "keeper_name": owner.keeper_name or "",
                "keeper_phone": owner.keeper_phone or "",
                "road": road,
                "description": v["description"],
                "fine_amount_pence": penalty["fine_pence"],
                "points": penalty["points"],
                "timestamp": timestamp.isoformat(),
                "processing_time_ms": processing_time_ms,
            }
            created_violations.append(violation_data)

            logger.info(
                "VIOLATION %s: %s %s on %s - %s [%dms]",
                ref_number,
                v["type"].value,
                v["severity"].value,
                road,
                plate,
                processing_time_ms,
            )

    return created_violations
