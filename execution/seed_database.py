"""
Seed the PostgreSQL database with initial schema and reference data.

Creates tables for violations, subscribers, alert_log, and spatial
reference data. Loads initial speed limit zones and road network data.

Usage:
    python execution/seed_database.py

Env vars required:
    DATABASE_URL - PostgreSQL connection string
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

# SQL statements for schema creation
SCHEMA_SQL = """
-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- Traffic events table
CREATE TABLE IF NOT EXISTS traffic_events (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    source_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    description TEXT,
    location GEOGRAPHY(POINT, 4326),
    road VARCHAR(100),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source, source_id)
);

-- Violations table
CREATE TABLE IF NOT EXISTS violations (
    id BIGSERIAL PRIMARY KEY,
    violation_type VARCHAR(10) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    vehicle_id VARCHAR(20),
    location GEOGRAPHY(POINT, 4326),
    road VARCHAR(100),
    description TEXT,
    evidence_ref VARCHAR(255),
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    reviewed BOOLEAN DEFAULT FALSE
);

-- Subscribers table
CREATE TABLE IF NOT EXISTS subscribers (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255),
    phone VARCHAR(20),
    webhook_url TEXT,
    alert_channels TEXT[] DEFAULT '{"email"}',
    violation_types TEXT[] DEFAULT '{"ALL"}',
    location GEOGRAPHY(POINT, 4326),
    radius_km FLOAT DEFAULT 10.0,
    quiet_hours_start TIME DEFAULT '22:00',
    quiet_hours_end TIME DEFAULT '07:00',
    timezone VARCHAR(50) DEFAULT 'Europe/London',
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Alert log table
CREATE TABLE IF NOT EXISTS alert_log (
    id BIGSERIAL PRIMARY KEY,
    violation_id BIGINT REFERENCES violations(id),
    subscriber_id BIGINT REFERENCES subscribers(id),
    channel VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    error_message TEXT
);

-- Speed limit zones (spatial)
CREATE TABLE IF NOT EXISTS speed_limit_zones (
    id BIGSERIAL PRIMARY KEY,
    road VARCHAR(100) NOT NULL,
    speed_limit_mph INT NOT NULL,
    geometry GEOGRAPHY(LINESTRING, 4326),
    is_variable BOOLEAN DEFAULT FALSE,
    active BOOLEAN DEFAULT TRUE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_violations_timestamp ON violations(timestamp);
CREATE INDEX IF NOT EXISTS idx_violations_type ON violations(violation_type);
CREATE INDEX IF NOT EXISTS idx_violations_location ON violations USING GIST(location);
CREATE INDEX IF NOT EXISTS idx_traffic_events_timestamp ON traffic_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_subscribers_location ON subscribers USING GIST(location);
CREATE INDEX IF NOT EXISTS idx_speed_limit_zones_geom ON speed_limit_zones USING GIST(geometry);
"""


def seed_database():
    """Create schema and seed initial data."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)

    try:
        import psycopg2

        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        cur.execute(SCHEMA_SQL)
        conn.commit()
        logger.info("Database schema created successfully")

        cur.close()
        conn.close()
    except ImportError:
        logger.error("psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)
    except Exception:
        logger.exception("Failed to seed database")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_database()
