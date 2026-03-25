# VANS UK — Agent Instructions

> This file is mirrored across `CLAUDE.md`, `AGENTS.md`, and `GEMINI.md` so the same instructions
> load in any AI environment. Preserve all three files identically when updating.

---

## What This System Is

**VANS UK** (Vehicle Alert Notification System UK) is a real-time driver violation detection and
notification platform for the United Kingdom — a Belloite Ltd product.

When a driver commits a traffic violation (speeding, red-light, no insurance, etc.) they receive
an SMS within seconds. The pipeline:

```
ANPR Camera → Plate Read → DVLA Lookup → Violation Check → Instant SMS
     │              │            │              │               │
  <1 sec         <1 sec       <2 sec         <1 sec          <3 sec
                                                        ─────────────
                                                        Total: <10 sec
```

Target audience: **DVLA** and **National Highways** — this system should be presentation-ready
at any time. Scalable, observable, documented.

---

## 3-Layer Architecture

You operate across three layers. Never collapse them.

### Layer 1 — Directives (`directives/`)
- Markdown SOPs. Plain language. Like instructions to a senior engineer.
- Define: goal, inputs, tools/scripts to call, expected output, edge cases.
- **Living documents** — update them when you learn something new.
- Never delete a directive without asking. Add, refine, correct.

### Layer 2 — Orchestration (You)
- Read the directive. Decide the order of execution scripts to call.
- Handle errors. Retry where safe. Ask when unsure.
- You are the intelligent glue between intent and deterministic code.
- Do NOT do the work yourself when a script exists. Call the script.

### Layer 3 — Execution (`execution/`)
- Deterministic Python scripts. One job each. Well-commented.
- All secrets/tokens in `.env` — never hardcode credentials.
- Scripts are reliable, testable, observable. Use them.

---

## Operating Principles

### 1. Check for existing tools first
Before writing a script, check `execution/` and the relevant directive.
Create new scripts only if nothing fits.

### 2. Self-anneal when things break

When a script fails:
1. Read the full error + stack trace
2. Understand the root cause (don't just retry)
3. Fix the script
4. Test the fix
5. Update the directive with what you learned (API quirks, rate limits, etc.)
6. The system is now stronger

> Exception: if the failure involves paid API calls (Twilio, SendGrid, DVLA) — pause and
> check with the user before running again.

### 3. Update directives as you learn
Found an API rate limit? A better endpoint? A timing edge case? Write it into the directive.
Directives are your long-term memory. Keep them accurate.

### 4. Keep intermediates out of git
- `.tmp/` — all intermediate files (scraped data, temp exports, processing artifacts)
- Never commit `.tmp/`, `.env`, `credentials.json`, `token.json`
- Deliverables live in cloud services or the database — not local files

### 5. Minimal changes
Only change what the task requires. Do not refactor surrounding code.
Do not add features that weren't requested. Three similar lines beat a premature abstraction.

---

## Directory Structure

```
VANS-UK/
├── CLAUDE.md                          # Agent instructions (this file)
├── AGENTS.md                          # Mirror of CLAUDE.md
├── GEMINI.md                          # Mirror of CLAUDE.md
├── README.md                          # Human-readable project overview
├── src/
│   ├── api/
│   │   ├── main.py                    # FastAPI app — serves API + static frontend
│   │   └── routes/
│   │       ├── anpr.py                # ANPR submission + simulation endpoints
│   │       ├── violations.py          # Violation CRUD + stats
│   │       ├── traffic.py             # Traffic incidents + roadworks
│   │       ├── subscriptions.py       # Subscriber management
│   │       └── system.py              # Health, readiness, metrics
│   ├── ingestion/
│   │   ├── anpr_processor.py          # Normalise + validate ANPR camera reads
│   │   └── dvla_lookup.py             # DVLA VES API with 24h caching
│   ├── processing/
│   │   └── violation_engine.py        # Core violation detection logic
│   ├── alerting/
│   │   └── notification_service.py    # Twilio SMS + SendGrid email dispatch
│   └── models/
│       ├── orm.py                     # SQLAlchemy ORM models (8 tables)
│       ├── schemas.py                 # Pydantic request/response schemas
│       └── database.py                # Async PostgreSQL connection + table init
├── static/
│   └── index.html                     # Futuristic dashboard SPA (served at /)
├── execution/                         # Standalone deterministic scripts
│   ├── detect_speed_violation.py      # Standalone speed violation checker
│   ├── seed_database.py               # Seed schema + test data
│   ├── ingest_highways.py             # National Highways API ingestion
│   ├── ingest_tfl.py                  # TfL API ingestion
│   ├── send_email_alert.py            # Standalone SendGrid email dispatch
│   └── send_sms_alert.py              # Standalone Twilio SMS dispatch
├── directives/                        # Workflow SOPs (update as you learn)
│   ├── detect_violations.md
│   ├── ingest_traffic_data.md
│   ├── send_alerts.md
│   └── manage_api.md
├── tests/
│   └── test_models.py                 # Unit tests
├── config/
│   └── sources.yaml                   # External API endpoints
├── .env.example                       # Environment variable template
├── Dockerfile                         # Single-stage Railway-compatible build
├── docker-compose.yml                 # Local dev (PostgreSQL + API)
├── railway.toml                       # Railway deployment config
└── requirements.txt                   # Python dependencies
```

---

## Key External Services

| Service | Purpose | Env vars |
|---------|---------|----------|
| DVLA VES API | Vehicle keeper + tax/MOT status | `DVLA_API_KEY` |
| Twilio | Instant SMS notifications | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` |
| SendGrid | Email notifications | `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL` |
| National Highways | Traffic incidents + roadworks | `NATIONAL_HIGHWAYS_API_KEY` |
| TfL | London disruption data | `TFL_APP_KEY` |

---

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

---

## Tech Stack

- **Language**: Python 3.11+
- **API**: FastAPI with full async/await
- **Database**: PostgreSQL (Railway-managed), SQLAlchemy async ORM
- **HTTP Client**: httpx (async)
- **SMS**: Twilio
- **Email**: SendGrid
- **Frontend**: Vanilla HTML/CSS/JS SPA served as static files
- **Deployment**: Railway.com (single container, auto-SSL, managed Postgres)
- **Testing**: pytest + pytest-asyncio

---

## Development Commands

```bash
# Local development
pip install -r requirements.txt
uvicorn src.api.main:app --reload --port 8000

# Run tests
pytest tests/ -v

# Docker (local full stack)
docker-compose up --build

# ANPR simulation — generates realistic UK plates + violations
curl -X POST http://localhost:8000/api/v1/anpr/simulate \
  -H "Content-Type: application/json" \
  -d '{"readings_per_second": 10, "duration_seconds": 30}'
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard frontend (HTML) |
| GET | `/health` | Liveness check |
| GET | `/ready` | Readiness check (DB connectivity) |
| GET | `/api/docs` | Swagger UI |
| GET | `/api/v1/violations` | List violations (paginated, filtered) |
| GET | `/api/v1/violations/stats` | Aggregated stats |
| GET | `/api/v1/violations/{id}` | Get single violation |
| POST | `/api/v1/anpr/readings` | Submit ANPR reading |
| POST | `/api/v1/anpr/simulate` | Start violation simulation |
| GET | `/api/v1/metrics` | System metrics |
| WS | `/ws/violations` | Real-time violation stream |

---

## Self-Annealing Loop Reference

```
Error occurs
    │
    ▼
Read full error + stack trace
    │
    ▼
Identify root cause
    │
    ├─ Script bug?    → Fix script → Test → Update directive
    ├─ API change?    → Update script + directive with new contract
    ├─ Rate limit?    → Add backoff/batching → Update directive
    ├─ Missing data?  → Add fallback → Update directive
    └─ Paid API?      → STOP → Ask user before retrying
```

---

## Railway Deployment Notes

- Environment variables set in Railway dashboard (not committed to repo)
- `DATABASE_URL` or `PGHOST`/`PGUSER`/`PGPASSWORD`/`PGDATABASE` auto-injected by Railway Postgres
- `PORT` injected by Railway — uvicorn binds to it automatically
- SSL enforced for DB connections in production
- Single container: API + violation engine + notification service all in-process
- Static frontend served from `static/index.html` at the root route `/`
