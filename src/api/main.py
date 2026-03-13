"""
VANS UK - FastAPI Application

Vehicle Alert Notification System for the UK.
Provides REST API and WebSocket endpoints for traffic violations and alerts.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="VANS UK API",
    description="Vehicle Alert Notification System - Real-Time Driver Violation Alerts for the UK",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict to configured origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "vans-uk"}


@app.get("/api/v1/traffic/incidents")
async def get_incidents():
    """Get current traffic incidents."""
    # TODO: Query from database
    return {"incidents": [], "count": 0}


@app.get("/api/v1/violations")
async def get_violations():
    """Query violations with filters."""
    # TODO: Implement with database queries and filtering
    return {"violations": [], "count": 0}


@app.get("/api/v1/violations/stats")
async def get_violation_stats():
    """Get aggregated violation statistics."""
    # TODO: Implement aggregation queries
    return {"stats": {}}
