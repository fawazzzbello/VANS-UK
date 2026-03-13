# VANS UK - Vehicle Alert Notification System UK

Real-Time Driver Violation Alerts and Traffic Information for the UK.

## Project Overview

VANS UK monitors UK roads for driver violations (speeding, red-light running, illegal turns, etc.) and delivers real-time alerts to relevant authorities and subscribers. It also aggregates and serves general traffic information (congestion, incidents, roadworks).

## 3-Layer Architecture

This project follows a 3-layer architecture that separates concerns for reliability:

### Layer 1: Directives (`directives/`)
- SOPs written in Markdown
- Define goals, inputs, tools/scripts, outputs, and edge cases
- Natural language instructions for each workflow

### Layer 2: Orchestration (AI Agent)
- Reads directives, calls execution tools in the right order
- Handles errors, asks for clarification, updates directives with learnings
- Routes between intent and execution

### Layer 3: Execution (`execution/`)
- Deterministic Python scripts
- Handle API calls, data processing, file operations, database interactions
- Reliable, testable, fast

## Directory Structure

```
VANS-UK/
├── CLAUDE.md              # This file - project instructions
├── directives/            # Layer 1: SOPs and workflow definitions
├── execution/             # Layer 3: Deterministic Python scripts
├── src/                   # Core application source code
│   ├── ingestion/         # Data ingestion from cameras, sensors, APIs
│   ├── processing/        # Violation detection and data processing
│   ├── alerting/          # Notification and alert delivery
│   ├── api/               # REST API for external consumers
│   ├── models/            # Data models and schemas
│   └── utils/             # Shared utilities
├── tests/                 # Test suite
├── config/                # Configuration files
├── .tmp/                  # Intermediate files (gitignored, regenerated)
└── .env                   # Environment variables (gitignored)
```

## Key Data Sources (UK-Specific)

- **DVLA** - Driver and Vehicle Licensing Agency data
- **Highways England / National Highways** - Traffic flow and incident data
- **ANPR** - Automatic Number Plate Recognition camera feeds
- **TfL** - Transport for London open data APIs
- **Police API** - UK Police data API for incident correlation
- **OS Maps** - Ordnance Survey mapping data

## Operating Principles

1. **Check for tools first** - Before writing a script, check `execution/`. Only create new scripts if none exist.
2. **Self-anneal when things break** - Read errors, fix scripts, update directives with learnings.
3. **Update directives as you learn** - Directives are living documents. Update when you discover constraints, better approaches, or edge cases.
4. **Deliverables vs Intermediates** - Deliverables go to cloud services. Intermediates go to `.tmp/` and are never committed.

## Tech Stack

- **Language**: Python 3.11+
- **Async Framework**: FastAPI
- **Message Queue**: Redis Streams (for real-time event processing)
- **Database**: PostgreSQL with PostGIS (geospatial queries)
- **Cache**: Redis
- **Task Queue**: Celery (for background processing)
- **Testing**: pytest

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -v

# Run the API server (development)
uvicorn src.api.main:app --reload --port 8000

# Run linting
ruff check src/ tests/

# Run type checking
mypy src/
```
