# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""
VANS UK - FastAPI Application

Vehicle Alert Notification System for the UK.
Production-grade REST API with full CRUD, pagination,
WebSocket real-time alerts, and DVLA integration.
Serves the futuristic dashboard at the root route.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import violations, traffic, subscriptions, system, anpr, admin
from src.api.routes.anpr import process_and_notify
from src.ingestion.anpr_processor import generate_reading
from src.models.database import init_db
import src.models.orm  # noqa: F401 — ensures all ORM models register with Base.metadata

logger = logging.getLogger(__name__)

# Static files directory
STATIC_DIR = Path(__file__).parent.parent.parent / "static"

# ── ANPR background task state ────────────────────────────────────────────────
# Controlled via POST /api/v1/admin/anpr/stop and /start
anpr_running: bool = True


async def _perpetual_anpr():
    """
    Background task: continuously generate and process ANPR readings.

    Runs at ~2 readings/second while anpr_running is True.
    Pauses (checks every second) when anpr_running is False.
    Violations are broadcast to all connected WebSocket clients.
    """
    await asyncio.sleep(3)  # let DB fully initialise first
    logger.info("Perpetual ANPR background task started (2 reads/sec)")
    while True:
        if not anpr_running:
            await asyncio.sleep(1)
            continue
        raw = generate_reading()
        try:
            result = await process_and_notify(raw)
            for v in result.get("violations", []):
                await manager.broadcast({"event": "violation", "data": v})
        except Exception:
            logger.exception("Background ANPR task error")
        await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    await init_db()
    asyncio.create_task(_perpetual_anpr())
    yield


app = FastAPI(
    title="VANS UK API",
    description=(
        "Vehicle Alert Notification System - Real-Time Driver Violation "
        "Alerts for the United Kingdom. Instant SMS notifications for "
        "traffic violations. A Belloite Ltd product."
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
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])

# Serve static assets (CSS, JS, images) if the static directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    """Broadcast real-time violation events to all connected WebSocket clients."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info("WebSocket client connected. Total: %d", len(self.active))

    def disconnect(self, ws: WebSocket):
        self.active = [c for c in self.active if c is not ws]
        logger.info("WebSocket client disconnected. Total: %d", len(self.active))

    async def broadcast(self, payload: dict):
        """Send a JSON payload to all connected clients, dropping dead connections."""
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


@app.websocket("/ws/violations")
async def ws_violations(ws: WebSocket):
    """
    WebSocket endpoint — streams live violation events to connected dashboards.

    Clients receive JSON objects on each new violation:
      {
        "event": "violation",
        "data": { ...ViolationResponse fields... }
      }

    Also sends a heartbeat ping every 30 seconds to keep the connection alive.
    """
    await manager.connect(ws)
    try:
        while True:
            # Keep the connection alive; data is pushed via manager.broadcast()
            await asyncio.sleep(30)
            try:
                await ws.send_text(json.dumps({"event": "ping"}))
            except Exception:
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


# ── Root route — serve the dashboard ─────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def dashboard():
    """Serve the VANS UK futuristic dashboard frontend."""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index), media_type="text/html")
    # Fallback if static files are not present
    return HTMLResponse(content=_fallback_html(), status_code=200)


def _fallback_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>VANS UK</title>
  <style>
    body{background:#060810;color:#e8f4fd;font-family:Inter,sans-serif;
         display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
    .box{text-align:center;padding:3rem;border:1px solid rgba(0,180,255,.2);border-radius:16px}
    h1{font-size:2rem;background:linear-gradient(135deg,#00c8ff,#0066ff);
       -webkit-background-clip:text;-webkit-text-fill-color:transparent}
    a{color:#00c8ff;text-decoration:none}
  </style>
</head>
<body>
  <div class="box">
    <h1>VANS UK</h1>
    <p style="color:rgba(180,210,240,.7);margin:1rem 0">Vehicle Alert Notification System</p>
    <p><a href="/api/docs">API Documentation →</a></p>
    <p><a href="/health">System Health →</a></p>
  </div>
</body>
</html>"""
