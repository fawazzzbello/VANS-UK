"""
detect_zone_violation.py — Congestion / ULEZ / Bus lane zone violation checker

Determines whether a vehicle plate was observed inside a restricted zone
(Congestion Charge, ULEZ, Clean Air Zone, Bus Lane) at a given time.

Usage:
    python execution/detect_zone_violation.py --plate AB12CDE --zone CON
    python execution/detect_zone_violation.py --plate AB12CDE --zone ULEZ --lat 51.5 --lon -0.1

Zone types:
    CON    — London Congestion Charge Zone (Mon-Fri 07:00-18:00, Sat-Sun 12:00-18:00)
    ULEZ   — Ultra Low Emission Zone (all hours, all days)
    BUS    — Bus Lane (varies by road, default 07:00-19:00 Mon-Fri)
    CAZ    — Clean Air Zone (city-specific)

Environment variables (.env):
    DATABASE_URL or PG* variables
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Zone definitions ───────────────────────────────────────────────────────────

# Approximate London Congestion Charge Zone bounding box
# Real implementation uses PostGIS polygon queries
ZONE_BOUNDS = {
    "CON": {
        "lat_min": 51.493, "lat_max": 51.522,
        "lon_min": -0.143, "lon_max": -0.069,
        "fine_pence": 16000,  # £160
        "active_hours": {
            "weekday": (7, 18),   # 07:00–18:00 Mon–Fri
            "weekend": (12, 18),  # 12:00–18:00 Sat–Sun (excluding bank holidays)
        },
        "description": "London Congestion Charge Zone",
    },
    "ULEZ": {
        # Greater London ULEZ (all London boroughs from Aug 2023)
        "lat_min": 51.28, "lat_max": 51.69,
        "lon_min": -0.51, "lon_max": 0.33,
        "fine_pence": 18000,  # £180 for cars (£1,000 for HGVs)
        "active_hours": {"all": True},
        "description": "Ultra Low Emission Zone",
    },
    "BUS": {
        "fine_pence": 6500,  # £65
        "active_hours": {"weekday": (7, 19)},
        "description": "Bus Lane",
    },
}


def is_zone_active(zone_key: str, dt: datetime) -> bool:
    """Check if a zone is active at the given datetime."""
    zone = ZONE_BOUNDS.get(zone_key, {})
    hours = zone.get("active_hours", {})

    if hours.get("all"):
        return True

    weekday = dt.weekday()  # 0=Mon, 6=Sun
    hour = dt.hour

    if weekday < 5:  # Monday–Friday
        wday = hours.get("weekday")
        return wday is not None and wday[0] <= hour < wday[1]
    else:  # Saturday–Sunday
        wend = hours.get("weekend")
        return wend is not None and wend[0] <= hour < wend[1]


def is_in_zone(zone_key: str, lat: float, lon: float) -> bool:
    """Simple bounding-box check. Production uses PostGIS polygon."""
    zone = ZONE_BOUNDS.get(zone_key)
    if not zone or "lat_min" not in zone:
        return True  # BUS lanes don't have a bounding box — assume in zone
    return (
        zone["lat_min"] <= lat <= zone["lat_max"]
        and zone["lon_min"] <= lon <= zone["lon_max"]
    )


def check_zone_violation(
    plate: str,
    zone_key: str,
    lat: float = 51.507,
    lon: float = -0.128,
    observed_at: datetime | None = None,
) -> dict:
    """
    Determine if a vehicle committed a zone-based violation.

    Returns a dict with: violation (bool), reason, fine_pence, zone_description.
    """
    dt = observed_at or datetime.now(timezone.utc)
    zone = ZONE_BOUNDS.get(zone_key)

    if not zone:
        return {"violation": False, "reason": f"Unknown zone: {zone_key}"}

    in_zone = is_in_zone(zone_key, lat, lon)
    active = is_zone_active(zone_key, dt)

    if not in_zone:
        return {
            "violation": False,
            "reason": f"Vehicle not inside {zone['description']} boundary",
            "plate": plate,
            "zone": zone_key,
        }

    if not active:
        return {
            "violation": False,
            "reason": f"{zone['description']} not active at {dt.strftime('%H:%M')}",
            "plate": plate,
            "zone": zone_key,
        }

    # TODO: for ULEZ — check vehicle emissions standard via DVLA lookup
    # Non-compliant vehicles: pre-Euro 4 petrol, pre-Euro 6 diesel, older motorbikes
    # For now, flag all vehicles as non-compliant (demo mode)

    return {
        "violation": True,
        "plate": plate.upper().replace(" ", ""),
        "zone": zone_key,
        "zone_description": zone["description"],
        "fine_pence": zone["fine_pence"],
        "fine_pounds": zone["fine_pence"] / 100,
        "observed_at": dt.isoformat(),
        "location": {"lat": lat, "lon": lon},
        "reason": f"Vehicle detected inside {zone['description']} during active hours",
    }


async def main():
    parser = argparse.ArgumentParser(description="Zone violation checker")
    parser.add_argument("--plate", required=True, help="UK registration plate")
    parser.add_argument(
        "--zone", required=True, choices=["CON", "ULEZ", "BUS", "CAZ"],
        help="Zone type"
    )
    parser.add_argument("--lat", type=float, default=51.507, help="Latitude (default: central London)")
    parser.add_argument("--lon", type=float, default=-0.128, help="Longitude (default: central London)")
    args = parser.parse_args()

    result = check_zone_violation(args.plate, args.zone, args.lat, args.lon)

    if result["violation"]:
        print(f"✅ VIOLATION DETECTED")
        print(f"   Plate  : {result['plate']}")
        print(f"   Zone   : {result['zone_description']}")
        print(f"   Fine   : £{result['fine_pounds']:.0f}")
        print(f"   Reason : {result['reason']}")
    else:
        print(f"✗  No violation: {result['reason']}")


if __name__ == "__main__":
    asyncio.run(main())
