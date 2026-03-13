# VANS UK

## Vehicle Alert Notification System for the United Kingdom

**Real-time traffic violation detection and instant driver notification, modeled on Dubai's RTA system.**

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
   number plate      with 95%+ confidence    via DVLA VES API   against limits     via Twilio
                                                                                 ──────────
                                                                          End-to-end: <10 seconds
```

### Key Capabilities

- **Instant Notifications**: SMS delivered within 10 seconds of violation detection
- **DVLA Integration**: Direct vehicle enquiry service integration for keeper identification
- **ANPR Processing**: High-throughput camera feed processing with confidence filtering
- **10 Violation Types**: Speeding, red lights, bus lanes, no insurance/MOT/tax, phone use, seatbelts, congestion charge, illegal turns
- **UK Penalty Schedule**: Correct fines and penalty points per violation type
- **Horizontal Scaling**: Redis Streams consumer groups allow unlimited worker scaling
- **Real-Time Dashboard API**: Full REST API with filtering, pagination, and statistics
- **Built-In Simulator**: Generate realistic ANPR test data for demonstrations

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                              │
│  ┌──────────┐  ┌──────────────┐  ┌─────┐  ┌──────────────────┐ │
│  │   ANPR   │  │   National   │  │ TfL │  │   UK Police API  │ │
│  │ Cameras  │  │   Highways   │  │ API │  │                  │ │
│  └────┬─────┘  └──────┬───────┘  └──┬──┘  └────────┬─────────┘ │
└───────┼───────────────┼─────────────┼───────────────┼───────────┘
        │               │             │               │
        ▼               ▼             ▼               ▼
┌─────────────────────────────────────────────────────────────────┐
│                     REDIS STREAMS                                │
│  ┌─────────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ anpr_readings    │  │ violations   │  │  notifications    │  │
│  │ (consumer groups)│  │              │  │                   │  │
│  └────────┬─────────┘  └──────┬───────┘  └─────────┬─────────┘  │
└───────────┼───────────────────┼──────────────────────┼──────────┘
            │                   │                      │
            ▼                   ▼                      ▼
┌───────────────────┐ ┌─────────────────┐ ┌─────────────────────┐
│ VIOLATION ENGINE  │ │  DVLA LOOKUP    │ │ NOTIFICATION SERVICE│
│ (scalable workers)│ │  (cached)       │ │ (scalable workers)  │
│                   │ │                 │ │                     │
│ • Speed detection │ │ • Vehicle info  │ │ • SMS via Twilio    │
│ • Tax/MOT check   │ │ • Keeper details│ │ • Email via SendGrid│
│ • Insurance check │ │ • 24hr cache    │ │ • Delivery tracking │
└───────────────────┘ └─────────────────┘ └─────────────────────┘
            │                                        │
            ▼                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    POSTGRESQL + PostGIS                           │
│  violations │ subscribers │ alert_log │ speed_limit_zones        │
│  traffic_events │ vehicle_lookup_cache │ anpr_readings           │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FASTAPI REST API                            │
│  /violations  │  /traffic  │  /subscriptions  │  /anpr          │
│  /violations/stats  │  /health  │  /ready  │  /metrics          │
└─────────────────────────────────────────────────────────────────┘
```

### Scalability

The system is designed for horizontal scaling via Redis Streams consumer groups:

| Component | Scaling Method | Default Replicas |
|-----------|---------------|-----------------|
| API Server | uvicorn workers + load balancer | 4 workers |
| ANPR Processor | Consumer group members | 2 replicas |
| Violation Engine | Consumer group members | 3 replicas |
| Notification Service | Consumer group members | 2 replicas |

Scale up with a single command:
```bash
docker-compose up --scale violation-engine=10 --scale notification-service=5
```

### Quick Start

```bash
# 1. Clone and configure
git clone <repo-url> && cd VANS-UK
cp .env.example .env
# Fill in API keys: DVLA_API_KEY, TWILIO_*, SENDGRID_API_KEY

# 2. Start the full system
docker-compose up --build

# 3. Run a demo simulation (generates realistic ANPR data)
curl -X POST http://localhost:8000/api/v1/anpr/simulate \
  -H "Content-Type: application/json" \
  -d '{"readings_per_second": 50, "duration_seconds": 60}'

# 4. Check violations
curl http://localhost:8000/api/v1/violations/stats

# 5. View API documentation
open http://localhost:8000/api/docs
```

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Liveness check |
| GET | `/ready` | Readiness check (DB + Redis) |
| GET | `/api/v1/violations` | Query violations with filters |
| GET | `/api/v1/violations/stats` | Dashboard statistics |
| GET | `/api/v1/violations/{id}` | Single violation detail |
| GET | `/api/v1/violations/ref/{ref}` | Lookup by reference number |
| GET | `/api/v1/traffic/incidents` | Current traffic incidents |
| GET | `/api/v1/traffic/roadworks` | Active roadworks |
| POST | `/api/v1/anpr/readings` | Submit ANPR reading |
| POST | `/api/v1/anpr/readings/batch` | Submit batch (up to 1000) |
| POST | `/api/v1/anpr/simulate` | Start demo simulation |
| POST | `/api/v1/subscriptions` | Create alert subscription |
| GET | `/api/v1/metrics` | System metrics |

### UK Penalty Schedule

| Violation | Fine | Points | Severity |
|-----------|------|--------|----------|
| Speeding (1-5mph over) | £100 | 3 | LOW |
| Speeding (5-10mph over) | £100 | 3 | MEDIUM |
| Speeding (10-20mph over) | £100 | 3 | HIGH |
| Speeding (20mph+ over) | £100 | 3 | CRITICAL |
| Red Light Running | £100 | 3 | HIGH |
| Bus Lane Violation | £65 | 0 | MEDIUM |
| Congestion Charge Evasion | £160 | 0 | MEDIUM |
| No Insurance | £300 | 6 | CRITICAL |
| No MOT | £1,000 | 0 | HIGH |
| No Vehicle Tax | £1,000 | 0 | HIGH |
| Phone Use While Driving | £200 | 6 | HIGH |
| Seatbelt Violation | £500 | 0 | MEDIUM |

### DVLA Integration

VANS UK integrates with the DVLA Vehicle Enquiry Service (VES) API for:

- **Vehicle identification**: Make, model, colour, year
- **Compliance checks**: Tax status, MOT status, insurance status
- **Keeper identification**: Registered keeper name and contact details (requires DVLA partnership)
- **Smart caching**: 24-hour cache reduces API calls and improves response times

For production deployment with DVLA, the system would connect via the government's secure API gateway, providing access to full keeper details including contact information for instant SMS delivery.

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

### Technology Stack

- **Python 3.11+** with async/await throughout
- **FastAPI** for high-performance REST API
- **Redis Streams** for real-time event processing with consumer groups
- **PostgreSQL + PostGIS** for geospatial data and violations storage
- **SQLAlchemy 2.0** async ORM with Pydantic validation
- **Twilio** for instant SMS delivery
- **SendGrid** for email notifications
- **Docker Compose** for containerised deployment
- **pytest** for comprehensive testing

### License

Proprietary. For DVLA evaluation purposes only.
