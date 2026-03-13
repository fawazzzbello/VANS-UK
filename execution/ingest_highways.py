"""
Ingest traffic data from National Highways (NTIS) Datex II feed.

Polls the National Highways API for traffic incidents, roadworks, and
variable message sign data. Normalizes responses into the common
TrafficEvent schema and publishes to Redis Streams.

Usage:
    python execution/ingest_highways.py

Env vars required:
    HIGHWAYS_API_KEY - National Highways API key
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

HIGHWAYS_BASE_URL = "https://api.nationalhighways.co.uk"
POLL_INTERVAL_SECONDS = 60


async def fetch_incidents(client: httpx.AsyncClient, api_key: str) -> list[dict]:
    """Fetch current incidents from National Highways API."""
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    resp = await client.get(
        f"{HIGHWAYS_BASE_URL}/v1/traffic/incidents",
        headers=headers,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json().get("features", [])


def normalize_incident(raw: dict) -> TrafficEvent:
    """Convert a National Highways incident to a TrafficEvent."""
    props = raw.get("properties", {})
    geometry = raw.get("geometry", {})
    coords = geometry.get("coordinates", [0, 0])

    return TrafficEvent(
        source="national_highways",
        source_id=props.get("id", ""),
        event_type=props.get("type", "INCIDENT"),
        severity=props.get("severity", "UNKNOWN"),
        description=props.get("description", ""),
        latitude=coords[1] if len(coords) >= 2 else 0.0,
        longitude=coords[0] if len(coords) >= 2 else 0.0,
        road=props.get("road", ""),
        timestamp=datetime.now(timezone.utc),
    )


async def publish_events(r: redis.Redis, events: list[TrafficEvent]) -> int:
    """Publish normalized events to Redis Streams."""
    count = 0
    for event in events:
        await r.xadd("traffic_events", event.to_dict())
        count += 1
    return count


async def run_once(client: httpx.AsyncClient, r: redis.Redis, api_key: str) -> int:
    """Execute a single poll cycle."""
    raw_incidents = await fetch_incidents(client, api_key)
    events = [normalize_incident(inc) for inc in raw_incidents]
    published = await publish_events(r, events)
    logger.info("Published %d events from National Highways", published)
    return published


async def main():
    """Main polling loop."""
    api_key = os.environ.get("HIGHWAYS_API_KEY")
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    if not api_key:
        logger.error("HIGHWAYS_API_KEY not set")
        sys.exit(1)

    r = redis.from_url(redis_url)
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await run_once(client, r, api_key)
            except httpx.HTTPStatusError as e:
                logger.error("HTTP error from Highways API: %s", e)
            except Exception:
                logger.exception("Unexpected error in Highways ingestion")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
