"""
ANPR (Automatic Number Plate Recognition) Camera Feed Processor.

Normalizes raw ANPR readings and feeds them into the violation detection
pipeline. Works entirely in-process - no Redis required.

In production, this would connect to:
- Police ANPR infrastructure (NACP)
- Local authority camera systems
- Highways England speed cameras
- TfL enforcement cameras
"""

import logging
import random
import string
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Minimum confidence threshold for ANPR reads to be processed
MIN_CONFIDENCE = 0.80


def normalize_reading(raw: dict[str, Any]) -> dict[str, Any] | None:
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
        "confidence": confidence,
        "observed_speed_mph": raw.get("observed_speed_mph"),
        "latitude": float(raw.get("latitude", 0)),
        "longitude": float(raw.get("longitude", 0)),
        "direction": str(raw.get("direction", "")),
        "lane": raw.get("lane"),
        "road": str(raw.get("road", "")),
        "speed_limit": raw.get("speed_limit"),
        "image_ref": str(raw.get("image_ref", "")),
        "timestamp": str(raw.get("timestamp", datetime.now(timezone.utc).isoformat())),
    }


# ─── ANPR Simulator (for demos and load testing) ───────────────

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


def generate_reading() -> dict[str, Any]:
    """Generate a single realistic ANPR reading for simulation."""
    letters1 = "".join(random.choices(string.ascii_uppercase, k=2))
    numbers = "".join(random.choices(string.digits, k=2))
    letters2 = "".join(random.choices(string.ascii_uppercase, k=3))
    plate = f"{letters1}{numbers}{letters2}"

    road_info = random.choice(SAMPLE_ROADS)

    # 80% within limit, 20% speeding
    if random.random() < 0.20:
        speed = road_info["limit"] + random.randint(1, 40)
    else:
        speed = road_info["limit"] - random.randint(0, 15)
    speed = max(speed, 5)

    return {
        "camera_id": random.choice(SAMPLE_CAMERAS),
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
