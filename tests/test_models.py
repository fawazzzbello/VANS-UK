"""Tests for data models, core business logic, and pipeline functions."""

from datetime import datetime, timezone

import pytest

from src.models.schemas import (
    ViolationCreate,
    SubscriberCreate,
    VehicleOwner,
)


# ─── Violation Detection Logic ──────────────────────────────

class TestSpeedViolationDetection:
    def test_classify_severity_critical(self):
        from src.processing.violation_engine import classify_speed_severity, Severity
        assert classify_speed_severity(25) == Severity.CRITICAL

    def test_classify_severity_high(self):
        from src.processing.violation_engine import classify_speed_severity, Severity
        assert classify_speed_severity(15) == Severity.HIGH

    def test_classify_severity_medium(self):
        from src.processing.violation_engine import classify_speed_severity, Severity
        assert classify_speed_severity(7) == Severity.MEDIUM

    def test_classify_severity_low(self):
        from src.processing.violation_engine import classify_speed_severity, Severity
        assert classify_speed_severity(3) == Severity.LOW

    def test_reference_number_format(self):
        from src.processing.violation_engine import generate_reference_number
        ref = generate_reference_number()
        assert ref.startswith("VN-")
        parts = ref.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 5  # 5 hex chars

    def test_penalty_schedule_completeness(self):
        from src.processing.violation_engine import PENALTY_SCHEDULE, ViolationType
        for vtype in ViolationType:
            assert vtype in PENALTY_SCHEDULE, f"Missing penalty for {vtype}"
            penalty = PENALTY_SCHEDULE[vtype]
            assert "fine_pence" in penalty
            assert "points" in penalty
            assert penalty["fine_pence"] > 0


# ─── Pydantic Schema Validation ─────────────────────────────

class TestViolationCreate:
    def test_plate_normalization(self):
        v = ViolationCreate(
            violation_type="SPD",
            severity="HIGH",
            vehicle_plate="ab 12 cde",
            latitude=51.5,
            longitude=-0.1,
            timestamp=datetime.now(timezone.utc),
        )
        assert v.vehicle_plate == "AB12CDE"

    def test_invalid_latitude_rejected(self):
        with pytest.raises(Exception):
            ViolationCreate(
                violation_type="SPD",
                severity="HIGH",
                vehicle_plate="AB12CDE",
                latitude=91.0,  # invalid
                longitude=0,
                timestamp=datetime.now(timezone.utc),
            )

    def test_valid_creation(self):
        v = ViolationCreate(
            violation_type="RLR",
            severity="CRITICAL",
            vehicle_plate="XY99ZZZ",
            latitude=51.5074,
            longitude=-0.1278,
            road="A40",
            observed_speed=45.0,
            speed_limit=30,
            timestamp=datetime.now(timezone.utc),
        )
        assert v.violation_type == "RLR"
        assert v.observed_speed == 45.0


class TestSubscriberCreate:
    def test_default_channels(self):
        s = SubscriberCreate(name="Test User")
        assert s.alert_channels == ["SMS"]

    def test_plate_normalization(self):
        s = SubscriberCreate(name="Test", vehicle_plate="ab 12 cde")
        assert s.vehicle_plate == "AB12CDE"

    def test_none_plate_allowed(self):
        s = SubscriberCreate(name="Test", vehicle_plate=None)
        assert s.vehicle_plate is None


class TestVehicleOwner:
    def test_minimal_creation(self):
        owner = VehicleOwner(vehicle_plate="AB12CDE")
        assert owner.make is None
        assert owner.keeper_name is None

    def test_full_creation(self):
        owner = VehicleOwner(
            vehicle_plate="AB12CDE",
            make="BMW",
            model="3 Series",
            colour="Black",
            year=2022,
            fuel_type="Petrol",
            tax_status="Taxed",
            mot_status="Valid",
            keeper_name="John Smith",
            keeper_phone="+447700900000",
            insurance_status="Insured",
        )
        assert owner.make == "BMW"
        assert owner.keeper_phone == "+447700900000"


# ─── Notification Formatting ────────────────────────────────

class TestNotificationFormatting:
    def test_sms_format(self):
        from src.alerting.notification_service import format_sms_message
        msg = format_sms_message({
            "reference_number": "VN-20260313-A1B2C",
            "violation_type": "SPD",
            "road": "M25",
            "description": "85mph in 70mph zone",
            "fine_amount_pence": "10000",
            "points": "3",
            "timestamp": "2026-03-13T14:30:00+00:00",
        })
        assert "VN-20260313-A1B2C" in msg
        assert "SPD" in msg
        assert "M25" in msg
        assert "£100.00" in msg
        assert "3 points" in msg
        assert "28 days" in msg

    def test_sms_no_points(self):
        from src.alerting.notification_service import format_sms_message
        msg = format_sms_message({
            "reference_number": "VN-20260313-X9Y8Z",
            "violation_type": "BUS",
            "road": "A40",
            "description": "Bus lane violation",
            "fine_amount_pence": "6500",
            "points": "0",
            "timestamp": "2026-03-13T14:30:00+00:00",
        })
        assert "£65.00" in msg
        assert "points" not in msg

    def test_email_format(self):
        from src.alerting.notification_service import format_violation_email_html
        subject, html = format_violation_email_html({
            "reference_number": "VN-20260313-A1B2C",
            "violation_type": "SPD",
            "severity": "HIGH",
            "vehicle_plate": "AB12CDE",
            "road": "M25",
            "description": "85mph in 70mph zone",
            "fine_amount_pence": "10000",
            "points": "3",
            "keeper_name": "John Smith",
            "timestamp": "2026-03-13T14:30:00+00:00",
        })
        assert "VN-20260313-A1B2C" in subject
        assert "John Smith" in html
        assert "AB12CDE" in html
        assert "Pay Fine Online" in html


# ─── ANPR Processing ────────────────────────────────────────

class TestANPRProcessing:
    def test_normalize_reading_valid(self):
        from src.ingestion.anpr_processor import normalize_reading
        result = normalize_reading({
            "camera_id": "CAM-M25-J10-N",
            "vehicle_plate": "AB12 CDE",
            "confidence": "0.95",
            "observed_speed_mph": "85",
            "latitude": "51.47",
            "longitude": "-0.45",
            "road": "M25",
            "timestamp": "2026-03-13T14:30:00+00:00",
        })
        assert result is not None
        assert result["vehicle_plate"] == "AB12CDE"
        assert result["source"] == "anpr"

    def test_normalize_reading_low_confidence(self):
        from src.ingestion.anpr_processor import normalize_reading
        result = normalize_reading({
            "camera_id": "CAM-M25-J10-N",
            "vehicle_plate": "AB12 CDE",
            "confidence": "0.50",  # Below threshold
            "latitude": "51.47",
            "longitude": "-0.45",
        })
        assert result is None

    def test_normalize_reading_empty_plate(self):
        from src.ingestion.anpr_processor import normalize_reading
        result = normalize_reading({
            "camera_id": "CAM-M25-J10-N",
            "vehicle_plate": "",
            "confidence": "0.95",
            "latitude": "51.47",
            "longitude": "-0.45",
        })
        assert result is None

    def test_generate_reading(self):
        from src.ingestion.anpr_processor import generate_reading
        reading = generate_reading()
        assert "camera_id" in reading
        assert "vehicle_plate" in reading
        assert "confidence" in reading
        assert "observed_speed_mph" in reading
        assert "latitude" in reading
        assert "longitude" in reading
        assert len(reading["vehicle_plate"]) == 7


# ─── DVLA Lookup ─────────────────────────────────────────────

class TestDVLALookup:
    def test_parse_dvla_response(self):
        from src.ingestion.dvla_lookup import DVLALookupService
        service = DVLALookupService.__new__(DVLALookupService)
        owner = service._parse_dvla_response("AB12CDE", {
            "make": "BMW",
            "colour": "BLACK",
            "yearOfManufacture": 2022,
            "fuelType": "PETROL",
            "taxStatus": "Taxed",
            "taxDueDate": "2027-03-01",
            "motStatus": "Valid",
            "motExpiryDate": "2027-06-15",
        })
        assert owner.make == "BMW"
        assert owner.colour == "BLACK"
        assert owner.year == 2022
        assert owner.tax_status == "Taxed"

    def test_parse_empty_response(self):
        from src.ingestion.dvla_lookup import DVLALookupService
        service = DVLALookupService.__new__(DVLALookupService)
        owner = service._parse_dvla_response("AB12CDE", {})
        assert owner.vehicle_plate == "AB12CDE"
        assert owner.make is None

    def test_check_tax_mot_flags(self):
        """Test that tax/MOT check returns correct boolean flags."""
        owner = VehicleOwner(
            vehicle_plate="AB12CDE",
            tax_status="Taxed",
            mot_status="Valid",
        )
        has_tax = owner.tax_status in ("Taxed", "SORN")
        has_mot = owner.mot_status in ("Valid", "No results returned")
        assert has_tax is True
        assert has_mot is True

        untaxed = VehicleOwner(
            vehicle_plate="XY99ZZZ",
            tax_status="Untaxed",
            mot_status="Not valid",
        )
        has_tax = untaxed.tax_status in ("Taxed", "SORN")
        has_mot = untaxed.mot_status in ("Valid", "No results returned")
        assert has_tax is False
        assert has_mot is False
