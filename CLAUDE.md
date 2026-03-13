# VANS UK - Vehicle Alert Notification System UK

Real-Time Driver Violation Alerts for the United Kingdom.
Inspired by Dubai's RTA instant notification system - when a driver commits a violation,
they receive an SMS within seconds.

## How It Works

```
ANPR Camera → Plate Read → DVLA Lookup → Violation Check → Instant SMS
     │              │            │              │               │
  <1 sec         <1 sec       <2 sec         <1 sec          <3 sec
                                                        ─────────────
                                                        Total: <10 sec
```

## 3-Layer Architecture

### Layer 1: Directives (`directives/`)
- SOPs in Markdown: goals, inputs, tools, outputs, edge cases

### Layer 2: Orchestration (AI Agent)
- Reads directives, calls execution tools, handles errors, updates directives

### Layer 3: Execution (`execution/`)
- Deterministic Python scripts for API calls, data processing, DB operations

## Directory Structure

```
VANS-UK/
├── CLAUDE.md                          # Project instructions
├── src/
│   ├── ingestion/
│   │   ├── anpr_processor.py          # ANPR camera feed processor (consumer groups)
│   │   └── dvla_lookup.py             # DVLA Vehicle Enquiry Service integration
│   ├── processing/
│   │   └── violation_engine.py        # Real-time violation detection engine
│   ├── alerting/
│   │   └── notification_service.py    # Instant SMS/email notification (Dubai-style)
│   ├── api/
│   │   ├── main.py                    # FastAPI application
│   │   └── routes/                    # API route modules
│   └── models/
│       ├── orm.py                     # SQLAlchemy ORM models
│       ├── schemas.py                 # Pydantic request/response schemas
│       └── database.py                # Async DB connection management
├── execution/                         # Standalone execution scripts
├── directives/                        # Workflow SOPs
├── tests/                             # Test suite
├── config/                            # Configuration files
├── Dockerfile                         # Multi-stage Docker build
├── docker-compose.yml                 # Full system deployment
└── .env.example                       # Environment variable template
```

## Key Data Sources

- **DVLA VES API** - Vehicle enquiry, keeper details, tax/MOT status
- **ANPR Cameras** - Number plate reads with speed measurements
- **National Highways** - Traffic flow and incident data
- **TfL** - Transport for London disruption data

## Tech Stack

- **Language**: Python 3.11+
- **API**: FastAPI with async/await
- **Message Queue**: Redis Streams (consumer groups for horizontal scaling)
- **Database**: PostgreSQL + PostGIS (geospatial queries)
- **SMS**: Twilio
- **Email**: SendGrid
- **Deployment**: Docker Compose with scalable workers
- **Testing**: pytest

## Development Commands

```bash
# Full system (Docker)
docker-compose up --build

# Scale workers for load
docker-compose up --build --scale violation-engine=5 --scale notification-service=3

# Local development
pip install -r requirements.txt
uvicorn src.api.main:app --reload --port 8000

# Run tests
pytest tests/ -v

# ANPR simulation (for demos)
curl -X POST http://localhost:8000/api/v1/anpr/simulate \
  -H "Content-Type: application/json" \
  -d '{"readings_per_second": 50, "duration_seconds": 60}'
```

## Violation Types

| Code | Type | Fine | Points |
|------|------|------|--------|
| SPD | Speeding | £100 | 3 |
| RLR | Red Light Running | £100 | 3 |
| BUS | Bus Lane | £65 | 0 |
| CON | Congestion Charge | £160 | 0 |
| INS | No Insurance | £300 | 6 |
| MOT | No MOT | £1,000 | 0 |
| TAX | No Vehicle Tax | £1,000 | 0 |
| PHN | Phone Use | £200 | 6 |
| SBT | Seatbelt | £500 | 0 |
