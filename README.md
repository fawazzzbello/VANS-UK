# VANS UK

## Vehicle Alert Notification System for the United Kingdom

**Real-time traffic violation detection and instant driver notification, modelled on Dubai's RTA system.**

---

### The Problem

The UK currently has no unified system for instantly notifying drivers of traffic violations. Penalties arrive by post days or weeks later, reducing their deterrent effect and creating administrative overhead.

Dubai's Roads and Transport Authority (RTA) solved this: when a driver commits a violation, they receive an SMS notification within seconds. This system has been credited with significantly improving road safety compliance.

### The Solution

VANS UK replicates Dubai's instant notification model for the UK road network:

```
ANPR Camera Read → Vehicle Identification → DVLA Lookup → Violation Detection → Instant SMS
      │                    │                      │                │                  │
   Camera reads      Plate recognised        Owner identified   Rules checked      SMS sent
   number plate      with 80%+ confidence    via DVLA VES API   against limits     via Twilio
                                                                               ──────────────
                                                                        End-to-end: <10 seconds
```

### Key Capabilities

- **Instant Notifications**: SMS delivered within 10 seconds of violation detection
- **DVLA Integration**: Vehicle Enquiry Service API for keeper identification with 24-hour caching
- **ANPR Processing**: Camera feed normalisation with 80% confidence threshold filtering
- **10 Violation Types**: Speeding, red lights, illegal turns, bus lanes, no insurance/MOT/tax, phone use, seatbelts, congestion charge
- **UK Penalty Schedule**: Correct fines and penalty points per violation type
- **In-Process Pipeline**: Single FastAPI app handles ANPR → detection → notification end-to-end, no message broker required
- **Real-Time Dashboard**: WebSocket push for live violation events + full REST API
- **Built-In Simulator**: Generate realistic ANPR test data for demonstrations

---

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                              │
│  ┌──────────┐  ┌──────────────┐  ┌─────┐                        │
│  │   ANPR   │  │   National   │  │ TfL │                        │
│  │ Cameras  │  │   Highways   │  │ API │                        │
│  └────┬─────┘  └──────┬───────┘  └──┬──┘                        │
└───────┼───────────────┼─────────────┼─────────────────────────────┘
        │               │             │
        ▼               ▼             ▼
┌──────────────────────────────────────────────────────────────────┐
│               FASTAPI — IN-PROCESS PIPELINE                       │
│                                                                   │
│  ┌──────────────────┐   ┌─────────────────┐   ┌───────────────┐  │
│  │  ANPR Processor  │──▶│ Violation Engine │──▶│ Notification  │  │
│  │ • Normalise      │   │ • Speed check    │   │ Service       │  │
│  │ • Validate plate │   │ • DVLA tax/MOT   │   │ • SMS Twilio  │  │
│  │ • Confidence ≥80%│   │ • Insurance      │   │ • Email SG    │  │
│  └──────────────────┘   └────────┬────────┘   └───────────────┘  │
│                                  │                                │
│                          ┌───────▼────────┐                       │
│                          │  DVLA Lookup   │                       │
│                          │  (24h cache)   │                       │
│                          └────────────────┘                       │
└──────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      POSTGRESQL DATABASE                          │
│  violations │ subscribers │ alert_log │ speed_limit_zones        │
│  traffic_events │ vehicle_lookup_cache │ anpr_readings           │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   REST API + WEBSOCKET                            │
│  /violations  │  /traffic  │  /subscriptions  │  /anpr          │
│  /violations/stats  │  /health  │  /ready  │  /metrics          │
│  ws://.../ws/violations  (real-time violation push)              │
└─────────────────────────────────────────────────────────────────┘
```

---

### Quick Start

#### Local development (Docker)

```bash
# 1. Clone and configure
git clone <repo-url> && cd VANS-UK
cp .env.example .env
# Edit .env — fill in DVLA_API_KEY, TWILIO_*, SENDGRID_API_KEY (see below)

# 2. Start PostgreSQL + API
docker-compose up --build

# 3. Run a demo simulation (generates realistic ANPR readings)
curl -X POST http://localhost:8000/api/v1/anpr/simulate \
  -H "Content-Type: application/json" \
  -d '{"readings_per_second": 10, "duration_seconds": 30}'

# 4. Check violations detected
curl http://localhost:8000/api/v1/violations/stats

# 5. Browse the dashboard and API docs
open http://localhost:8000          # Live dashboard
open http://localhost:8000/api/docs # Swagger UI
```

#### Run without Docker

```bash
pip install -r requirements.txt

# Set DATABASE_URL to a running PostgreSQL instance
export DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/vans_uk

python start.py        # reads PORT from env, defaults to 8000
# or:
uvicorn src.api.main:app --reload --port 8000
```

---

### Environment Variables

Copy `.env.example` to `.env` and fill in values. On Railway, `DATABASE_URL` and `PORT` are injected automatically — do not set them manually.

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes (local) | PostgreSQL connection string. Railway injects this automatically. |
| `DVLA_API_KEY` | For full functionality | DVLA Vehicle Enquiry Service API key. Without it, plate lookups return no keeper details. |
| `TWILIO_ACCOUNT_SID` | For SMS | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | For SMS | Twilio auth token |
| `TWILIO_FROM_NUMBER` | For SMS | Twilio sender number (e.g. `+441234567890`) |
| `SENDGRID_API_KEY` | For email | SendGrid API key |
| `SENDGRID_FROM_EMAIL` | For email | Sender address (e.g. `alerts@vans-uk.example.com`) |
| `NATIONAL_HIGHWAYS_API_KEY` | Optional | National Highways incident data |
| `TFL_APP_KEY` | Optional | Transport for London disruption data |
| `TEST_SMS_RECIPIENT` | Optional | Phone number to receive test SMS without a real DVLA keeper record |
| `JWT_SECRET_KEY` | Recommended | Secret for JWT signing. Change from default before production. |
| `CORS_ORIGINS` | Optional | Comma-separated allowed CORS origins. Default: `*` |
| `LOG_LEVEL` | Optional | Logging level (`INFO`, `DEBUG`, `WARNING`). Default: `INFO` |

**Minimum to get SMS alerts working:**
```
DVLA_API_KEY=...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+44...
```

**Railway deployment:** Set all of the above via the Railway dashboard under *Variables*. PostgreSQL and PORT are injected by Railway when you add the Postgres plugin.

---

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Live dashboard (HTML) |
| GET | `/health` | Liveness check — always 200 if running |
| GET | `/ready` | Readiness check — verifies database connectivity |
| GET | `/api/docs` | Swagger UI |
| GET | `/api/v1/violations` | Query violations (filters: type, severity, plate, road, status, date range) |
| GET | `/api/v1/violations/stats` | Aggregated statistics for dashboards |
| GET | `/api/v1/violations/{id}` | Single violation by ID |
| GET | `/api/v1/violations/ref/{ref}` | Lookup by reference number (e.g. `VN-20260313-A1B2C`) |
| POST | `/api/v1/anpr/readings` | Submit a single ANPR reading — triggers full pipeline immediately |
| POST | `/api/v1/anpr/readings/batch` | Submit up to 1,000 readings |
| POST | `/api/v1/anpr/simulate` | Start a simulation (configurable rps + duration) |
| GET | `/api/v1/traffic/incidents` | Traffic incidents (National Highways / TfL) |
| GET | `/api/v1/traffic/roadworks` | Active roadworks |
| POST | `/api/v1/subscriptions` | Register a subscriber for violation alerts |
| GET | `/api/v1/metrics` | System metrics (violation counts, alert success rate, avg latency) |
| WS | `/ws/violations` | WebSocket stream — real-time violation push to dashboards |

---

### UK Penalty Schedule

| Code | Violation | Fine | Points | Severity |
|------|-----------|------|--------|----------|
| SPD | Speeding (1–5 mph over) | £100 | 3 | LOW |
| SPD | Speeding (5–10 mph over) | £100 | 3 | MEDIUM |
| SPD | Speeding (10–20 mph over) | £100 | 3 | HIGH |
| SPD | Speeding (20 mph+ over) | £100 | 3 | CRITICAL |
| RLR | Red Light Running | £100 | 3 | HIGH |
| ILT | Illegal Turn | £100 | 3 | MEDIUM |
| BUS | Bus Lane Violation | £65 | 0 | MEDIUM |
| CON | Congestion Charge Evasion | £160 | 0 | MEDIUM |
| INS | No Insurance | £300 | 6 | CRITICAL |
| MOT | No MOT | £1,000 | 0 | HIGH |
| TAX | No Vehicle Tax | £1,000 | 0 | HIGH |
| PHN | Phone Use While Driving | £200 | 6 | HIGH |
| SBT | Seatbelt Violation | £500 | 0 | MEDIUM |

---

### DVLA Integration

VANS UK integrates with the DVLA Vehicle Enquiry Service (VES) API for:

- **Vehicle identification**: Make, model, colour, year, fuel type
- **Compliance checks**: Tax status, MOT status, insurance status
- **Keeper identification**: Registered keeper name and contact details (requires DVLA partnership — the public VES API does not return keeper contact details)
- **Smart caching**: 24-hour cache per plate reduces API calls and speeds up repeat lookups

Without `DVLA_API_KEY` the system still processes ANPR readings and logs violations, but cannot send SMS notifications because no keeper phone number is available. For a demo, set `TEST_SMS_RECIPIENT` to receive test messages for any detected violation.

For production deployment with DVLA, the system would connect via the Government's secure API gateway, providing access to full keeper details for instant SMS delivery.

---

### SMS Notification Format

```
VANS UK Traffic Violation Notice
Ref: VN-20260313-A1B2C
Violation: SPD on M25
Travelling at 85mph in a 70mph zone (+15mph over limit)
Fine: £100.00 | 3 points
Date: 13/03/2026 14:30
Pay or appeal within 28 days at vans-uk.gov.uk/pay
Do not reply to this message.
```

---

### Technology Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ with full async/await |
| API | FastAPI 0.115 |
| Database | PostgreSQL (Railway-managed), SQLAlchemy 2.0 async ORM |
| HTTP Client | httpx (async) |
| WebSockets | websockets / FastAPI native |
| Static files | aiofiles (served via FastAPI StaticFiles) |
| SMS | Twilio REST API |
| Email | SendGrid |
| Deployment | Railway.com — single container, auto-SSL, managed Postgres |
| Testing | pytest + pytest-asyncio |
| Local dev | Docker Compose (Postgres + API) |

---

### Deployment (Railway)

1. Connect repo to Railway
2. Add a **PostgreSQL** plugin — `DATABASE_URL` is injected automatically
3. Set environment variables in the Railway dashboard (see table above)
4. Railway builds from `Dockerfile` and starts with `python start.py`
5. The `start.py` entry point reads `PORT` from the environment — no manual port config needed

The `/health` endpoint responds immediately without a database round-trip, so the Railway healthcheck will pass even during DB initialisation.

---

### License

Proprietary. For DVLA evaluation purposes only.
