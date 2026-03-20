# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""TrafficEvent model for normalized traffic data from all sources."""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class TrafficEvent:
    """A normalized traffic event from any data source."""

    source: str  # e.g. "national_highways", "tfl", "police"
    source_id: str  # unique ID from the source system
    event_type: str  # e.g. "INCIDENT", "ROADWORKS", "DISRUPTION"
    severity: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    description: str
    latitude: float
    longitude: float
    road: str  # road identifier, e.g. "M25", "A40"
    timestamp: datetime

    # Optional fields populated by enrichment
    observed_speed: float | None = None
    vehicle_id: str | None = None

    def to_dict(self) -> dict[str, str]:
        """Convert to a flat dict of strings for Redis Streams."""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        # Redis streams require string values
        return {k: str(v) if v is not None else "" for k, v in d.items()}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "TrafficEvent":
        """Reconstruct from a Redis Streams dict."""
        return cls(
            source=data.get("source", ""),
            source_id=data.get("source_id", ""),
            event_type=data.get("event_type", ""),
            severity=data.get("severity", ""),
            description=data.get("description", ""),
            latitude=float(data.get("latitude", 0)),
            longitude=float(data.get("longitude", 0)),
            road=data.get("road", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            observed_speed=(
                float(data["observed_speed"])
                if data.get("observed_speed")
                else None
            ),
            vehicle_id=data.get("vehicle_id") or None,
        )
