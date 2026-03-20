# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""Violation model for detected traffic violations."""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class Violation:
    """A detected traffic violation."""

    violation_type: str  # "SPD", "RLR", "ILT", "BUS", "CON", "INS"
    severity: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    vehicle_id: str  # number plate
    latitude: float
    longitude: float
    road: str
    description: str
    timestamp: datetime
    evidence_ref: str  # reference to camera/sensor evidence

    id: int | None = None
    reviewed: bool = False

    def to_dict(self) -> dict[str, str]:
        """Convert to a flat dict of strings for Redis Streams."""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return {k: str(v) if v is not None else "" for k, v in d.items()}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "Violation":
        """Reconstruct from a Redis Streams dict."""
        return cls(
            violation_type=data.get("violation_type", ""),
            severity=data.get("severity", ""),
            vehicle_id=data.get("vehicle_id", ""),
            latitude=float(data.get("latitude", 0)),
            longitude=float(data.get("longitude", 0)),
            road=data.get("road", ""),
            description=data.get("description", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            evidence_ref=data.get("evidence_ref", ""),
        )
