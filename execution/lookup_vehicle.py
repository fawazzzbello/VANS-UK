"""
lookup_vehicle.py — DVLA Vehicle Enquiry Service lookup

Fetches vehicle details for a given registration plate from the DVLA VES API.
Prints registration, make, colour, tax status, MOT status, and keeper postcode.

Usage:
    python execution/lookup_vehicle.py --plate AB12CDE
    python execution/lookup_vehicle.py --plate AB12CDE --json

Environment variables required (.env):
    DVLA_API_KEY    — DVLA Vehicle Enquiry Service API key
                      (apply at https://developer-portal.driver-vehicle-licensing.api.gov.uk/)

API docs:
    https://developer-portal.driver-vehicle-licensing.api.gov.uk/apis/vehicle-enquiry-service
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


DVLA_VES_URL = "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"
DVLA_VES_TEST_URL = "https://uat.driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"

TAX_STATUS_LABELS = {
    "Taxed": "✅ Taxed",
    "SORN": "⛔ SORN (off road)",
    "Untaxed": "❌ Untaxed",
}

MOT_STATUS_LABELS = {
    "Valid": "✅ Valid MOT",
    "No details held by DVLA": "⚠️  No MOT details",
    "Not valid": "❌ Invalid MOT",
}


async def lookup(plate: str, use_test_env: bool = False) -> dict:
    """Call the DVLA VES API and return raw vehicle data."""
    import httpx

    api_key = os.environ.get("DVLA_API_KEY", "")
    if not api_key:
        raise EnvironmentError("DVLA_API_KEY not set. Apply at https://developer-portal.driver-vehicle-licensing.api.gov.uk/")

    base_url = DVLA_VES_TEST_URL if use_test_env else DVLA_VES_URL
    plate_clean = plate.upper().replace(" ", "")

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {"registrationNumber": plate_clean}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(base_url, headers=headers, json=payload)

    if resp.status_code == 404:
        return {"error": f"Vehicle not found: {plate_clean}"}
    if resp.status_code == 400:
        return {"error": f"Invalid registration number: {plate_clean}"}
    if resp.status_code == 401:
        return {"error": "Invalid DVLA API key"}
    if resp.status_code == 429:
        return {"error": "DVLA API rate limit exceeded. Retry after 1 minute."}

    resp.raise_for_status()
    return resp.json()


def format_vehicle(data: dict) -> str:
    """Pretty-print vehicle details."""
    if "error" in data:
        return f"ERROR: {data['error']}"

    lines = [
        f"Registration : {data.get('registrationNumber', '—')}",
        f"Make         : {data.get('make', '—')}",
        f"Colour       : {data.get('colour', '—')}",
        f"Year         : {data.get('yearOfManufacture', '—')}",
        f"Engine (cc)  : {data.get('engineCapacity', '—')}",
        f"Fuel type    : {data.get('fuelType', '—')}",
        f"CO2 (g/km)   : {data.get('co2Emissions', '—')}",
        f"Tax status   : {TAX_STATUS_LABELS.get(data.get('taxStatus', ''), data.get('taxStatus', '—'))}",
        f"Tax due      : {data.get('taxDueDate', '—')}",
        f"MOT status   : {MOT_STATUS_LABELS.get(data.get('motStatus', ''), data.get('motStatus', '—'))}",
        f"MOT expiry   : {data.get('motExpiryDate', '—')}",
    ]
    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser(description="DVLA vehicle lookup")
    parser.add_argument("--plate", required=True, help="UK registration plate (e.g. AB12CDE)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--test", action="store_true", help="Use DVLA UAT/test environment")
    args = parser.parse_args()

    data = await lookup(args.plate, use_test_env=args.test)

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_vehicle(data))


if __name__ == "__main__":
    asyncio.run(main())
