# Directive: Manage API

## Goal
Expose a RESTful API for external consumers to query violations, traffic data, and manage subscriptions.

## API Endpoints

### Traffic Data
- `GET /api/v1/traffic/incidents` - Current traffic incidents
- `GET /api/v1/traffic/flow/{road_id}` - Traffic flow for a road
- `GET /api/v1/traffic/roadworks` - Active roadworks

### Violations
- `GET /api/v1/violations` - Query violations (with filters)
- `GET /api/v1/violations/{id}` - Single violation detail
- `GET /api/v1/violations/stats` - Aggregated statistics

### Subscriptions
- `POST /api/v1/subscriptions` - Create subscription
- `GET /api/v1/subscriptions/{id}` - Get subscription details
- `PUT /api/v1/subscriptions/{id}` - Update preferences
- `DELETE /api/v1/subscriptions/{id}` - Cancel subscription

### WebSocket
- `WS /api/v1/ws/alerts` - Real-time alert stream

## Authentication
- API Key for machine-to-machine
- JWT (OAuth2) for user-facing applications
- Rate limiting per API key tier

## Execution Scripts
- `execution/seed_database.py` - Seed database with initial data
- `execution/generate_api_docs.py` - Generate OpenAPI spec

## Edge Cases
- **Pagination**: Default 50, max 200 per page, cursor-based
- **Filtering**: Support geo-radius queries using PostGIS
- **Versioning**: URL-based (`/v1/`), maintain backward compatibility
- **CORS**: Allow configured origins only
