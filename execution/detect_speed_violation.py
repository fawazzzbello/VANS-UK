"""
Detect speed violations by comparing observed speeds against posted limits.

Consumes events from the traffic_events Redis Stream, checks vehicle speed
against the speed limit for that road segment (via PostGIS lookup), and
publishes confirmed violations to the violations stream.

Usage:
    python execution/detect_speed_violation.py

Env vars required:
    REDIS_URL - Redis connection string
    DATABASE_URL - PostgreSQL connection string (with PostGIS)
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import redis.asyncio as redis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models.violation import Violation

logger = logging.getLogger(__name__)

# Tolerance in mph before a violation is raised (accounts for measurement error)
SPEED_TOLERANCE_MPH = 2
# Confidence threshold below which violations are flagged for manual review
CONFIDENCE_THRESHOLD = 0.85


async def get_speed_limit(lat: float, lon: float, road: str) -> int | None:
    """
    Look up the posted speed limit for a road segment.

    In production, this queries PostGIS for the nearest road segment
    and returns its speed limit. Falls back to config-based lookup.
    """
    # TODO: Implement PostGIS spatial query
    # For now, return None to indicate lookup not yet available
    return None


def check_violation(
    observed_speed: float,
    speed_limit: int,
    tolerance: float = SPEED_TOLERANCE_MPH,
) -> tuple[bool, float]:
    """
    Determine if the observed speed constitutes a violation.

    Returns (is_violation, amount_over_limit).
    """
    effective_limit = speed_limit + tolerance
    if observed_speed > effective_limit:
        return True, observed_speed - speed_limit
    return False, 0.0


def classify_severity(amount_over: float) -> str:
    """Classify violation severity based on how far over the limit."""
    if amount_over >= 20:
        return "CRITICAL"
    elif amount_over >= 10:
        return "HIGH"
    elif amount_over >= 5:
        return "MEDIUM"
    return "LOW"


async def process_event(r: redis.Redis, event_data: dict) -> Violation | None:
    """Process a single traffic event for speed violations."""
    observed_speed = event_data.get("observed_speed")
    if observed_speed is None:
        return None

    observed_speed = float(observed_speed)
    lat = float(event_data.get("latitude", 0))
    lon = float(event_data.get("longitude", 0))
    road = event_data.get("road", "")

    speed_limit = await get_speed_limit(lat, lon, road)
    if speed_limit is None:
        logger.debug("No speed limit data for %s at (%.4f, %.4f)", road, lat, lon)
        return None

    is_violation, amount_over = check_violation(observed_speed, speed_limit)
    if not is_violation:
        return None

    severity = classify_severity(amount_over)

    return Violation(
        violation_type="SPD",
        severity=severity,
        vehicle_id=event_data.get("vehicle_id", ""),
        latitude=lat,
        longitude=lon,
        road=road,
        description=f"Speed {observed_speed:.0f}mph in {speed_limit}mph zone (+{amount_over:.0f}mph)",
        timestamp=datetime.now(timezone.utc),
        evidence_ref=event_data.get("source_id", ""),
    )


async def main():
    """Main consumer loop reading from traffic_events stream."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    r = redis.from_url(redis_url)

    last_id = "0-0"
    logger.info("Speed violation detector started")

    while True:
        try:
            results = await r.xread({"traffic_events": last_id}, count=100, block=5000)
            for stream_name, messages in results:
                for msg_id, data in messages:
                    last_id = msg_id
                    violation = await process_event(r, data)
                    if violation:
                        await r.xadd("violations", violation.to_dict())
                        logger.info("Violation detected: %s", violation.description)
        except Exception:
            logger.exception("Error in speed violation detection loop")
            await asyncio.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
