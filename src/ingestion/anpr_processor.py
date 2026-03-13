"""
ANPR (Automatic Number Plate Recognition) Camera Feed Processor.

Ingests readings from ANPR cameras deployed across UK roads, normalizes
them, and publishes to Redis Streams for real-time violation detection.

This is the primary data source for the Dubai-style instant notification
system. ANPR cameras capture:
- Vehicle registration plate
- Speed measurement
- Timestamp and location
- Direction of travel
- Confidence score of plate read
- Evidence image reference

In production, this would connect to:
- Police ANPR infrastructure (NACP - National ANPR Centre for Policing)
- Local authority camera systems
- Highways England speed cameras
- TfL enforcement cameras
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

logger = logging.getLogger(__name__)

# Minimum confidence threshold for ANPR reads to be processed
MIN_CONFIDENCE = 0.80

# Stream names
ANPR_INPUT_STREAM = "anpr_readings_raw"
ANPR_PROCESSED_STREAM = "anpr_readings"
CONSUMER_GROUP = "anpr_processors"


class ANPRProcessor:
    """
    Processes raw ANPR camera readings into normalized events.

    Designed to run as a scalable consumer group - multiple instances
    can process readings in parallel for high throughput.
    """

    def __init__(self, redis_client: redis.Redis, worker_id: str = "worker-1"):
        self.redis = redis_client
        self.worker_id = worker_id
        self._running = False

    async def start(self):
        """Start the ANPR processing loop."""
        await self._ensure_consumer_group()
        self._running = True
        logger.info("ANPR Processor %s started", self.worker_id)

        while self._running:
            try:
                await self._process_batch()
            except Exception:
                logger.exception("Error in ANPR processing loop")
                await asyncio.sleep(1)

    async def stop(self):
        """Gracefully stop the processor."""
        self._running = False
        logger.info("ANPR Processor %s stopping", self.worker_id)

    async def _ensure_consumer_group(self):
        """Create the consumer group if it doesn't exist."""
        try:
            await self.redis.xgroup_create(
                ANPR_INPUT_STREAM, CONSUMER_GROUP, id="0", mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def _process_batch(self):
        """Read and process a batch of ANPR readings."""
        results = await self.redis.xreadgroup(
            CONSUMER_GROUP,
            self.worker_id,
            {ANPR_INPUT_STREAM: ">"},
            count=100,
            block=5000,
        )

        if not results:
            return

        for stream_name, messages in results:
            for msg_id, data in messages:
                try:
                    processed = self._normalize_reading(data)
                    if processed:
                        await self.redis.xadd(ANPR_PROCESSED_STREAM, processed)
                        await self.redis.xack(
                            ANPR_INPUT_STREAM, CONSUMER_GROUP, msg_id
                        )
                    else:
                        logger.debug(
                            "Skipping low-confidence reading %s", msg_id
                        )
                        await self.redis.xack(
                            ANPR_INPUT_STREAM, CONSUMER_GROUP, msg_id
                        )
                except Exception:
                    logger.exception("Failed to process ANPR reading %s", msg_id)

    def _normalize_reading(self, raw: dict[str, Any]) -> dict[str, str] | None:
        """
        Normalize a raw ANPR reading into a processable event.

        Returns None if the reading should be skipped (low confidence, etc).
        """
        confidence = float(raw.get("confidence", 0))
        if confidence < MIN_CONFIDENCE:
            return None

        plate = str(raw.get("vehicle_plate", "")).upper().replace(" ", "").strip()
        if not plate or len(plate) < 2:
            return None

        return {
            "source": "anpr",
            "camera_id": str(raw.get("camera_id", "")),
            "camera_location": str(raw.get("camera_location", "")),
            "vehicle_plate": plate,
            "confidence": str(confidence),
            "observed_speed": str(raw.get("observed_speed_mph", "")),
            "latitude": str(raw.get("latitude", 0)),
            "longitude": str(raw.get("longitude", 0)),
            "direction": str(raw.get("direction", "")),
            "lane": str(raw.get("lane", "")),
            "road": str(raw.get("road", "")),
            "image_ref": str(raw.get("image_ref", "")),
            "timestamp": str(
                raw.get("timestamp", datetime.now(timezone.utc).isoformat())
            ),
        }

    async def submit_reading(self, reading: dict[str, Any]) -> str:
        """
        Submit an ANPR reading for processing.

        Used by camera integration modules to push readings into the pipeline.
        Returns the Redis Stream message ID.
        """
        # Ensure all values are strings for Redis Streams
        str_reading = {k: str(v) for k, v in reading.items()}
        msg_id = await self.redis.xadd(ANPR_INPUT_STREAM, str_reading)
        return msg_id


class ANPRSimulator:
    """
    Simulates ANPR camera readings for testing and demonstration.

    Generates realistic UK-format number plates, speeds, and locations
    for demo purposes and load testing.
    """

    # Sample UK roads with typical speed limits
    SAMPLE_ROADS = [
        {"road": "M25", "lat": 51.4700, "lon": -0.4500, "limit": 70},
        {"road": "M1", "lat": 51.8800, "lon": -0.4200, "limit": 70},
        {"road": "A40", "lat": 51.5155, "lon": -0.1750, "limit": 40},
        {"road": "A406", "lat": 51.5900, "lon": -0.1000, "limit": 50},
        {"road": "A13", "lat": 51.5100, "lon": 0.0800, "limit": 40},
        {"road": "M4", "lat": 51.4900, "lon": -0.6500, "limit": 70},
        {"road": "A2", "lat": 51.4400, "lon": 0.0700, "limit": 30},
        {"road": "M11", "lat": 51.7500, "lon": 0.0800, "limit": 70},
    ]

    SAMPLE_CAMERAS = [
        "CAM-M25-J10-N", "CAM-M25-J10-S", "CAM-M1-J6A-N",
        "CAM-A40-WX01-E", "CAM-A406-NE03-W", "CAM-A13-LB02-E",
        "CAM-M4-J4B-W", "CAM-A2-GR01-S", "CAM-M11-J7-N",
    ]

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.processor = ANPRProcessor(redis_client, "simulator")

    async def generate_reading(self) -> dict[str, Any]:
        """Generate a single realistic ANPR reading."""
        import random
        import string

        # Generate UK-format plate: AB12 CDE
        letters1 = "".join(random.choices(string.ascii_uppercase, k=2))
        numbers = "".join(random.choices(string.digits, k=2))
        letters2 = "".join(random.choices(string.ascii_uppercase, k=3))
        plate = f"{letters1}{numbers}{letters2}"

        road_info = random.choice(self.SAMPLE_ROADS)

        # 80% of vehicles within limit, 20% speeding
        if random.random() < 0.20:
            speed = road_info["limit"] + random.randint(1, 40)
        else:
            speed = road_info["limit"] - random.randint(0, 15)
        speed = max(speed, 5)

        return {
            "camera_id": random.choice(self.SAMPLE_CAMERAS),
            "camera_location": f"{road_info['road']} Speed Camera",
            "vehicle_plate": plate,
            "confidence": round(random.uniform(0.75, 0.99), 2),
            "observed_speed_mph": speed,
            "latitude": road_info["lat"] + random.uniform(-0.01, 0.01),
            "longitude": road_info["lon"] + random.uniform(-0.01, 0.01),
            "direction": random.choice(["N", "S", "E", "W"]),
            "lane": random.randint(1, 3),
            "road": road_info["road"],
            "image_ref": f"img-{plate}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "speed_limit": road_info["limit"],
        }

    async def run_simulation(self, readings_per_second: int = 10, duration_seconds: int = 60):
        """Run a simulation generating ANPR readings at a specified rate."""
        logger.info(
            "Starting ANPR simulation: %d readings/sec for %ds",
            readings_per_second,
            duration_seconds,
        )
        total = 0
        interval = 1.0 / readings_per_second

        for _ in range(duration_seconds * readings_per_second):
            reading = await self.generate_reading()
            await self.processor.submit_reading(reading)
            total += 1
            if total % 100 == 0:
                logger.info("Submitted %d ANPR readings", total)
            await asyncio.sleep(interval)

        logger.info("Simulation complete: %d total readings submitted", total)
        return total


async def main():
    """Run ANPR processor as standalone worker."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    worker_id = os.environ.get("WORKER_ID", "worker-1")

    r = redis.from_url(redis_url)
    processor = ANPRProcessor(r, worker_id)

    try:
        await processor.start()
    except KeyboardInterrupt:
        await processor.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
