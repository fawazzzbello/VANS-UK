"""Tests for data models."""

from datetime import datetime, timezone

from src.models.traffic_event import TrafficEvent
from src.models.violation import Violation


class TestTrafficEvent:
    def test_to_dict_roundtrip(self):
        event = TrafficEvent(
            source="tfl",
            source_id="tfl-123",
            event_type="INCIDENT",
            severity="HIGH",
            description="Multi-vehicle collision",
            latitude=51.5074,
            longitude=-0.1278,
            road="A40",
            timestamp=datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        )
        d = event.to_dict()
        restored = TrafficEvent.from_dict(d)
        assert restored.source == "tfl"
        assert restored.source_id == "tfl-123"
        assert restored.latitude == 51.5074
        assert restored.road == "A40"

    def test_optional_fields_default_none(self):
        event = TrafficEvent(
            source="test",
            source_id="1",
            event_type="TEST",
            severity="LOW",
            description="",
            latitude=0,
            longitude=0,
            road="",
            timestamp=datetime.now(timezone.utc),
        )
        assert event.observed_speed is None
        assert event.vehicle_id is None


class TestViolation:
    def test_to_dict_roundtrip(self):
        violation = Violation(
            violation_type="SPD",
            severity="HIGH",
            vehicle_id="AB12 CDE",
            latitude=51.5,
            longitude=-0.1,
            road="M25",
            description="Speed 85mph in 70mph zone (+15mph)",
            timestamp=datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            evidence_ref="cam-001-20260115",
        )
        d = violation.to_dict()
        restored = Violation.from_dict(d)
        assert restored.violation_type == "SPD"
        assert restored.vehicle_id == "AB12 CDE"
        assert restored.road == "M25"

    def test_severity_classification(self):
        from execution.detect_speed_violation import classify_severity

        assert classify_severity(25) == "CRITICAL"
        assert classify_severity(15) == "HIGH"
        assert classify_severity(7) == "MEDIUM"
        assert classify_severity(3) == "LOW"

    def test_speed_check(self):
        from execution.detect_speed_violation import check_violation

        is_v, over = check_violation(75, 70, tolerance=2)
        assert is_v is True
        assert over == 5

        is_v, over = check_violation(71, 70, tolerance=2)
        assert is_v is False
        assert over == 0.0
