# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""
send_sms_alert.py — Standalone Twilio SMS dispatcher

Reads a violation from the database by reference number and sends an SMS
to the registered keeper's phone number.

Usage:
    python execution/send_sms_alert.py --ref VN-20260314-A1B2C
    python execution/send_sms_alert.py --plate AB12CDE

Environment variables required (.env):
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_FROM_NUMBER     — E.164 format, e.g. +441234567890
    DATABASE_URL           — PostgreSQL connection string
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional — env vars may already be set


def _build_sms_body(violation: dict) -> str:
    """Format the SMS message body for a UK violation notice."""
    fine_pounds = violation.get("fine_amount_pence", 0) / 100
    type_labels = {
        "SPD": "Speeding", "RLR": "Red Light Running", "BUS": "Bus Lane",
        "CON": "Congestion Charge", "INS": "No Insurance", "MOT": "No MOT",
        "TAX": "No Vehicle Tax", "PHN": "Mobile Phone Use", "SBT": "No Seatbelt",
    }
    vtype = type_labels.get(violation.get("violation_type", ""), violation.get("violation_type", "Violation"))
    road = violation.get("road") or "Unknown location"
    ref = violation.get("reference_number", "—")
    points = violation.get("points", 0)

    lines = [
        "DVLA NOTICE — Traffic Violation",
        f"Ref: {ref}",
        f"Offence: {vtype}",
        f"Location: {road}",
        f"Fine: £{fine_pounds:.0f}",
    ]
    if points:
        lines.append(f"Penalty points: {points}")
    lines += [
        "Pay within 28 days to avoid surcharge.",
        "gov.uk/pay-penalty-charge",
    ]
    return "\n".join(lines)


async def send_sms(to_number: str, body: str) -> dict:
    """Send an SMS via Twilio REST API using httpx (async)."""
    import httpx

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = os.environ.get("TWILIO_FROM_NUMBER", "")

    if not all([account_sid, auth_token, from_number]):
        raise EnvironmentError(
            "Missing Twilio credentials: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER"
        )

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            url,
            auth=(account_sid, auth_token),
            data={"From": from_number, "To": to_number, "Body": body},
        )
        response.raise_for_status()
        data = response.json()
        return {
            "sid": data.get("sid"),
            "status": data.get("status"),
            "to": data.get("to"),
        }


async def main(ref: str | None = None, plate: str | None = None, dry_run: bool = False):
    """Fetch violation from DB and dispatch SMS."""
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        # Assemble from Railway components
        host = os.environ.get("PGHOST", "localhost")
        port = os.environ.get("PGPORT", "5432")
        user = os.environ.get("PGUSER", "postgres")
        pwd = os.environ.get("PGPASSWORD", "")
        name = os.environ.get("PGDATABASE", "vans_uk")
        db_url = f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{name}"

    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        if ref:
            result = await session.execute(
                text("SELECT * FROM violations WHERE reference_number = :ref"),
                {"ref": ref}
            )
        elif plate:
            plate_clean = plate.upper().replace(" ", "")
            result = await session.execute(
                text("SELECT * FROM violations WHERE vehicle_plate = :plate ORDER BY timestamp DESC LIMIT 1"),
                {"plate": plate_clean}
            )
        else:
            print("ERROR: Provide --ref or --plate")
            return

        row = result.mappings().first()
        if not row:
            print(f"No violation found for ref={ref} plate={plate}")
            return

        violation = dict(row)
        print(f"Violation: {violation['reference_number']} | {violation['violation_type']} | {violation['vehicle_plate']}")

        # For demo purposes — real system gets number from DVLA keeper record
        phone = os.environ.get("TEST_SMS_RECIPIENT", "")
        if not phone:
            print("No TEST_SMS_RECIPIENT set. Cannot send SMS without a verified phone number.")
            print("Set TEST_SMS_RECIPIENT=+441234567890 in .env to test.")
            return

        body = _build_sms_body(violation)
        print(f"\nSMS body:\n{'-'*40}\n{body}\n{'-'*40}")

        if dry_run:
            print("\n[DRY RUN] SMS not sent. Remove --dry-run to send.")
            return

        print(f"\nSending SMS to {phone}…")
        result = await send_sms(phone, body)
        print(f"Sent! SID={result['sid']} status={result['status']}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send violation SMS via Twilio")
    parser.add_argument("--ref", help="Violation reference number")
    parser.add_argument("--plate", help="Vehicle plate (sends for latest violation)")
    parser.add_argument("--dry-run", action="store_true", help="Print SMS but do not send")
    args = parser.parse_args()

    if not args.ref and not args.plate:
        parser.error("Provide --ref or --plate")

    asyncio.run(main(ref=args.ref, plate=args.plate, dry_run=args.dry_run))
