# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""
Ingest traffic data from Transport for London (TfL) Unified API.

Polls TfL for road disruptions, corridor status, and incident data.
Normalizes into TrafficEvent schema and publishes to Redis Streams.

Usage:
    python execution/ingest_tfl.py

Env vars required:
    TFL_APP_KEY - TfL API application key
    REDIS_URL - Redis connection string
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import httpx
import redis.asyncio as redis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models.traffic_event import TrafficEvent

logger = logging.getLogger(__name__)

TFL_BASE_URL = "https://api.tfl.gov.uk"
POLL_INTERVAL_SECONDS = 30


async def fetch_road_disruptions(client: httpx.AsyncClient, app_key: str) -> list[dict]:
    """Fetch current road disruptions from TfL."""
    params = {"app_key": app_key}
    resp = await client.get(
        f"{TFL_BASE_URL}/Road/all/Disruption",
        params=params,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def normalize_disruption(raw: dict) -> TrafficEvent:
    """Convert a TfL disruption to a TrafficEvent."""
    point = raw.get("point", "")
    lat, lon = 0.0, 0.0
    if point:
        # TfL point format: "POINT (lon lat)"
        try:
            coords = point.replace("POINT (", "").replace(")", "").split()
            lon, lat = float(coords[0]), float(coords[1])
        except (ValueError, IndexError):
            pass

    return TrafficEvent(
        source="tfl",
        source_id=raw.get("id", ""),
        event_type=raw.get("category", "DISRUPTION"),
        severity=raw.get("severity", "UNKNOWN"),
        description=raw.get("comments", raw.get("description", "")),
        latitude=lat,
        longitude=lon,
        road=raw.get("corridorIds", [""])[0] if raw.get("corridorIds") else "",
        timestamp=datetime.now(timezone.utc),
    )


async def publish_events(r: redis.Redis, events: list[TrafficEvent]) -> int:
    """Publish normalized events to Redis Streams."""
    count = 0
    for event in events:
        await r.xadd("traffic_events", event.to_dict())
        count += 1
    return count


async def main():
    """Main polling loop."""
    app_key = os.environ.get("TFL_APP_KEY")
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    if not app_key:
        logger.error("TFL_APP_KEY not set")
        sys.exit(1)

    r = redis.from_url(redis_url)
    async with httpx.AsyncClient() as client:
        while True:
            try:
                disruptions = await fetch_road_disruptions(client, app_key)
                events = [normalize_disruption(d) for d in disruptions]
                published = await publish_events(r, events)
                logger.info("Published %d events from TfL", published)
            except httpx.HTTPStatusError as e:
                logger.error("HTTP error from TfL API: %s", e)
            except Exception:
                logger.exception("Unexpected error in TfL ingestion")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
