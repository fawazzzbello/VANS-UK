# Directive: Ingest Traffic Data

## Goal
Pull real-time traffic and incident data from UK data sources and normalize it into a common schema for downstream processing.

## Data Sources

| Source | API | Rate Limit | Auth |
|--------|-----|-----------|------|
| National Highways (NTIS) | REST / Datex II | TBD | API Key |
| TfL Unified API | REST JSON | 500 req/min | App Key |
| UK Police API | REST JSON | 15 req/sec | None |
| HERE Traffic | REST JSON | Per plan | API Key |

## Inputs
- API credentials from `.env`
- Source configuration from `config/sources.yaml`

## Execution Scripts
- `execution/ingest_highways.py` - National Highways NTIS feed
- `execution/ingest_tfl.py` - TfL traffic disruptions and road status
- `execution/ingest_police.py` - UK Police incident data

## Output
- Normalized event records written to the message queue (Redis Streams)
- Schema: see `src/models/traffic_event.py`

## Edge Cases
- **Source downtime**: Log warning, continue with other sources, retry with exponential backoff
- **Schema changes**: Validate against expected schema; reject and alert on mismatches
- **Duplicate events**: Deduplicate by source ID + timestamp before publishing

## Scheduling
- National Highways: Poll every 60 seconds
- TfL: Poll every 30 seconds
- Police API: Poll every 5 minutes
