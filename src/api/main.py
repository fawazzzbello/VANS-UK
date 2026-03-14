"""
VANS UK - FastAPI Application

Vehicle Alert Notification System for the UK.
Production-grade REST API with JWT auth, full CRUD, pagination,
WebSocket real-time alerts, and DVLA integration.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from src.api.routes import violations, traffic, subscriptions, system, anpr
from src.models.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    await init_db()
    yield


app = FastAPI(
    title="VANS UK API",
    description=(
        "Vehicle Alert Notification System - Real-Time Driver Violation "
        "Alerts for the United Kingdom. Instant SMS notifications for "
        "traffic violations, modeled on Dubai's RTA system."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Security middleware
allowed_hosts = os.environ.get("ALLOWED_HOSTS", "*").split(",")
if allowed_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(system.router, tags=["System"])
app.include_router(violations.router, prefix="/api/v1", tags=["Violations"])
app.include_router(traffic.router, prefix="/api/v1", tags=["Traffic"])
app.include_router(subscriptions.router, prefix="/api/v1", tags=["Subscriptions"])
app.include_router(anpr.router, prefix="/api/v1", tags=["ANPR"])


@app.get("/")
async def root():
    """Landing page - confirms VANS UK API is running."""
    return {
        "service": "VANS UK",
        "description": "Vehicle Alert Notification System - Real-Time Driver Violation Alerts for the UK",
        "version": "1.0.0",
        "docs": "/api/docs",
        "health": "/health",
        "endpoints": {
            "anpr_submit": "/api/v1/anpr/readings",
            "violations": "/api/v1/violations",
            "stats": "/api/v1/violations/stats",
            "simulate": "/api/v1/anpr/simulate",
        },
    }
