"""ANPR endpoints - submit readings, query cameras, run simulations."""

import os

import redis.asyncio as redis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.ingestion.anpr_processor import ANPRProcessor, ANPRSimulator

router = APIRouter()


class ANPRReading(BaseModel):
    """Schema for submitting an ANPR camera reading."""

    camera_id: str
    camera_location: str | None = None
    vehicle_plate: str = Field(min_length=2, max_length=20)
    confidence: float = Field(ge=0, le=1)
    observed_speed_mph: float | None = None
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    direction: str | None = None
    lane: int | None = None
    road: str | None = None
    speed_limit: int | None = None
    image_ref: str | None = None
    timestamp: str | None = None


class SimulationRequest(BaseModel):
    readings_per_second: int = Field(10, ge=1, le=1000)
    duration_seconds: int = Field(60, ge=1, le=3600)


async def _get_redis() -> redis.Redis:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    return redis.from_url(redis_url)


@router.post("/anpr/readings", status_code=202)
async def submit_anpr_reading(reading: ANPRReading):
    """
    Submit a single ANPR camera reading for processing.

    The reading is added to the processing pipeline and will be checked
    for violations asynchronously. Returns immediately with a 202 Accepted.
    """
    r = await _get_redis()
    try:
        processor = ANPRProcessor(r)
        msg_id = await processor.submit_reading(reading.model_dump())
        return {
            "status": "accepted",
            "message_id": msg_id,
            "plate": reading.vehicle_plate.upper().replace(" ", ""),
        }
    finally:
        await r.aclose()


@router.post("/anpr/readings/batch", status_code=202)
async def submit_anpr_batch(readings: list[ANPRReading]):
    """Submit a batch of ANPR readings."""
    if len(readings) > 1000:
        raise HTTPException(
            status_code=400, detail="Maximum 1000 readings per batch"
        )

    r = await _get_redis()
    try:
        processor = ANPRProcessor(r)
        ids = []
        for reading in readings:
            msg_id = await processor.submit_reading(reading.model_dump())
            ids.append(msg_id)
        return {
            "status": "accepted",
            "count": len(ids),
        }
    finally:
        await r.aclose()


@router.post("/anpr/simulate", status_code=202)
async def start_simulation(req: SimulationRequest):
    """
    Start an ANPR simulation for testing and demonstration.

    Generates realistic UK number plates and speed readings at the
    specified rate. Useful for load testing and DVLA demos.
    """
    r = await _get_redis()
    simulator = ANPRSimulator(r)
    # Run simulation in background (non-blocking)
    import asyncio
    asyncio.create_task(
        simulator.run_simulation(req.readings_per_second, req.duration_seconds)
    )
    return {
        "status": "simulation_started",
        "readings_per_second": req.readings_per_second,
        "duration_seconds": req.duration_seconds,
        "total_expected": req.readings_per_second * req.duration_seconds,
    }
