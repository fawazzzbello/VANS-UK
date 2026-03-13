"""
Real-Time Violation Detection Engine.

The core processing engine that:
1. Consumes ANPR readings from Redis Streams (consumer group for scalability)
2. Looks up speed limits for the camera location
3. Detects violations (speeding, no tax, no MOT, no insurance)
4. Looks up vehicle owner via DVLA
5. Creates violation records
6. Triggers instant notification pipeline

Designed for horizontal scaling - multiple engine instances can process
readings in parallel via Redis consumer groups.

Target latency: ANPR read → SMS sent in under 10 seconds.
"""

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.dvla_lookup import DVLALookupService
from src.models.database import get_session
from src.models.orm import (
    ANPRReadingORM,
    SpeedLimitZoneORM,
    ViolationORM,
    ViolationType,
    Severity,
)

logger = logging.getLogger(__name__)

ANPR_STREAM = "anpr_readings"
VIOLATIONS_STREAM = "violations"
NOTIFICATION_STREAM = "notifications"
CONSUMER_GROUP = "violation_engines"

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


class ViolationEngine:
    """
    Main violation detection and processing engine.

    Runs as a consumer group member reading from ANPR streams,
    detecting violations, enriching with DVLA data, and triggering
    notifications.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        dvla_service: DVLALookupService,
        worker_id: str = "engine-1",
    ):
        self.redis = redis_client
        self.dvla = dvla_service
        self.worker_id = worker_id
        self._running = False
        self._stats = {
            "readings_processed": 0,
            "violations_detected": 0,
            "notifications_queued": 0,
        }

    async def start(self):
        """Start the violation engine processing loop."""
        await self._ensure_consumer_group()
        self._running = True
        logger.info("Violation Engine %s started", self.worker_id)

        while self._running:
            try:
                await self._process_batch()
            except Exception:
                logger.exception("Error in violation engine loop")
                await asyncio.sleep(1)

    async def stop(self):
        """Gracefully stop the engine."""
        self._running = False
        await self.dvla.close()
        logger.info(
            "Violation Engine %s stopped. Stats: %s", self.worker_id, self._stats
        )

    @property
    def stats(self) -> dict:
        return self._stats.copy()

    async def _ensure_consumer_group(self):
        """Create consumer group if it doesn't exist."""
        try:
            await self.redis.xgroup_create(
                ANPR_STREAM, CONSUMER_GROUP, id="0", mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def _process_batch(self):
        """Read and process a batch of ANPR readings."""
        results = await self.redis.xreadgroup(
            CONSUMER_GROUP,
            self.worker_id,
            {ANPR_STREAM: ">"},
            count=50,
            block=5000,
        )

        if not results:
            return

        for stream_name, messages in results:
            for msg_id, data in messages:
                start_time = time.monotonic()
                try:
                    await self._process_reading(data, start_time)
                    await self.redis.xack(ANPR_STREAM, CONSUMER_GROUP, msg_id)
                    self._stats["readings_processed"] += 1
                except Exception:
                    logger.exception("Failed to process reading %s", msg_id)

    async def _process_reading(self, data: dict, start_time: float):
        """Process a single ANPR reading for all violation types."""
        plate = data.get("vehicle_plate", "")
        if not plate:
            return

        observed_speed = data.get("observed_speed")
        speed_limit_str = data.get("speed_limit")
        lat = float(data.get("latitude", 0))
        lon = float(data.get("longitude", 0))
        road = data.get("road", "")
        camera_id = data.get("camera_id", "")
        image_ref = data.get("image_ref", "")
        timestamp_str = data.get("timestamp", "")

        try:
            timestamp = datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError):
            timestamp = datetime.now(timezone.utc)

        violations_found = []

        # 1. Check for speeding violation
        if observed_speed and speed_limit_str:
            speed = float(observed_speed)
            limit = int(float(speed_limit_str))
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
        async with get_session() as session:
            owner = await self.dvla.lookup_vehicle(plate, session)

            if owner.tax_status and owner.tax_status not in ("Taxed", "SORN"):
                violations_found.append({
                    "type": ViolationType.TAX,
                    "severity": Severity.HIGH,
                    "description": f"Vehicle tax status: {owner.tax_status}",
                })

            if owner.mot_status and owner.mot_status not in (
                "Valid", "No results returned", "Not valid"
            ):
                if owner.mot_status == "Not valid":
                    violations_found.append({
                        "type": ViolationType.MOT,
                        "severity": Severity.HIGH,
                        "description": f"MOT status: {owner.mot_status}. "
                        f"Expired: {owner.mot_expiry_date or 'unknown'}",
                    })

            if owner.insurance_status and owner.insurance_status != "Insured":
                violations_found.append({
                    "type": ViolationType.INS,
                    "severity": Severity.CRITICAL,
                    "description": (
                        f"No valid insurance. Status: {owner.insurance_status}"
                    ),
                })

            # 3. Create violation records and queue notifications
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
                    location_description=data.get("camera_location", ""),
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

                # Queue for instant notification
                notification_data = {
                    "violation_id": str(violation.id),
                    "reference_number": ref_number,
                    "violation_type": v["type"].value,
                    "severity": v["severity"].value,
                    "vehicle_plate": plate,
                    "keeper_name": owner.keeper_name or "",
                    "keeper_phone": owner.keeper_phone or "",
                    "road": road,
                    "description": v["description"],
                    "fine_amount_pence": str(penalty["fine_pence"]),
                    "points": str(penalty["points"]),
                    "timestamp": timestamp.isoformat(),
                    "processing_time_ms": str(processing_time_ms),
                }
                await self.redis.xadd(NOTIFICATION_STREAM, notification_data)
                self._stats["violations_detected"] += 1
                self._stats["notifications_queued"] += 1

                logger.info(
                    "VIOLATION %s: %s %s on %s - %s [%dms]",
                    ref_number,
                    v["type"].value,
                    v["severity"].value,
                    road,
                    plate,
                    processing_time_ms,
                )


async def main():
    """Run violation engine as standalone worker."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    worker_id = os.environ.get("WORKER_ID", "engine-1")

    r = redis.from_url(redis_url)
    dvla = DVLALookupService()
    engine = ViolationEngine(r, dvla, worker_id)

    try:
        await engine.start()
    except KeyboardInterrupt:
        await engine.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
