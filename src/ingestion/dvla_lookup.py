"""
DVLA Vehicle Enquiry Service Integration.

Provides instant vehicle and registered keeper lookup via the DVLA VES API.
This is the critical link that enables Dubai-style instant notifications -
when ANPR reads a plate, we look up the registered keeper to send them
an immediate SMS notification of their violation.

DVLA VES API: https://developer-portal.driver-vehicle-licensing.api.gov.uk/
Rate limit: 1000 requests/day on free tier, higher on enterprise agreement.

For DVLA presentation: This module would integrate with the DVLA's
internal systems directly via a secure government API gateway, bypassing
the public VES API rate limits.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.orm import VehicleLookupCacheORM
from src.models.schemas import VehicleOwner

logger = logging.getLogger(__name__)

DVLA_VES_URL = "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"

# Cache vehicle lookups for 24 hours to reduce API calls
CACHE_TTL_HOURS = 24


class DVLALookupService:
    """Service for looking up vehicle and keeper details via DVLA."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DVLA_API_KEY", "")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def lookup_vehicle(
        self,
        registration_number: str,
        session: AsyncSession | None = None,
    ) -> VehicleOwner:
        """
        Look up vehicle details by registration number.

        Checks cache first, then calls DVLA VES API if not cached.
        """
        plate = registration_number.upper().replace(" ", "").strip()

        # Check cache first
        if session:
            cached = await self._get_cached(session, plate)
            if cached:
                logger.debug("Cache hit for %s", plate)
                return cached

        # Call DVLA API
        owner = await self._call_dvla_api(plate)

        # Cache the result
        if session and owner:
            await self._cache_result(session, plate, owner)

        return owner

    async def _get_cached(
        self, session: AsyncSession, plate: str
    ) -> VehicleOwner | None:
        """Check if we have a fresh cached lookup for this plate."""
        result = await session.execute(
            select(VehicleLookupCacheORM).where(
                VehicleLookupCacheORM.vehicle_plate == plate,
                VehicleLookupCacheORM.expires_at > datetime.now(timezone.utc),
            )
        )
        cached = result.scalar_one_or_none()
        if not cached:
            return None

        return VehicleOwner(
            vehicle_plate=cached.vehicle_plate,
            make=cached.make,
            model=cached.model,
            colour=cached.colour,
            year=cached.year,
            fuel_type=cached.fuel_type,
            tax_status=cached.tax_status,
            tax_due_date=cached.tax_due_date,
            mot_status=cached.mot_status,
            mot_expiry_date=cached.mot_expiry_date,
            keeper_name=cached.keeper_name,
            keeper_phone=cached.keeper_phone,
            insurance_status=cached.insurance_status,
        )

    async def _call_dvla_api(self, plate: str) -> VehicleOwner:
        """Call the DVLA Vehicle Enquiry Service API."""
        if not self.api_key:
            logger.warning("DVLA_API_KEY not set, returning plate-only result")
            return VehicleOwner(vehicle_plate=plate)

        client = await self._get_client()
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {"registrationNumber": plate}

        try:
            resp = await client.post(DVLA_VES_URL, json=payload, headers=headers)

            if resp.status_code == 404:
                logger.info("Vehicle %s not found in DVLA records", plate)
                return VehicleOwner(vehicle_plate=plate)

            resp.raise_for_status()
            data = resp.json()
            return self._parse_dvla_response(plate, data)

        except httpx.HTTPStatusError as e:
            logger.error("DVLA API error for %s: %s", plate, e)
            return VehicleOwner(vehicle_plate=plate)
        except httpx.HTTPError as e:
            logger.error("DVLA API connection error for %s: %s", plate, e)
            return VehicleOwner(vehicle_plate=plate)

    def _parse_dvla_response(self, plate: str, data: dict[str, Any]) -> VehicleOwner:
        """Parse DVLA VES API response into VehicleOwner."""
        return VehicleOwner(
            vehicle_plate=plate,
            make=data.get("make"),
            model=data.get("model"),  # Not always returned by VES
            colour=data.get("colour"),
            year=data.get("yearOfManufacture"),
            fuel_type=data.get("fuelType"),
            tax_status=data.get("taxStatus"),
            tax_due_date=data.get("taxDueDate"),
            mot_status=data.get("motStatus"),
            mot_expiry_date=data.get("motExpiryDate"),
            # Note: VES public API doesn't return keeper details.
            # In production with DVLA partnership, we'd have access to:
            keeper_name=data.get("registeredKeeper", {}).get("name"),
            keeper_phone=data.get("registeredKeeper", {}).get("phone"),
            insurance_status=data.get("insuranceStatus"),
        )

    async def _cache_result(
        self, session: AsyncSession, plate: str, owner: VehicleOwner
    ):
        """Cache a DVLA lookup result."""
        expires = datetime.now(timezone.utc) + timedelta(hours=CACHE_TTL_HOURS)

        # Upsert - update if exists, insert if not
        existing = await session.execute(
            select(VehicleLookupCacheORM).where(
                VehicleLookupCacheORM.vehicle_plate == plate
            )
        )
        cached = existing.scalar_one_or_none()

        if cached:
            cached.make = owner.make
            cached.model = owner.model
            cached.colour = owner.colour
            cached.year = owner.year
            cached.fuel_type = owner.fuel_type
            cached.tax_status = owner.tax_status
            cached.tax_due_date = owner.tax_due_date
            cached.mot_status = owner.mot_status
            cached.mot_expiry_date = owner.mot_expiry_date
            cached.keeper_name = owner.keeper_name
            cached.keeper_phone = owner.keeper_phone
            cached.insurance_status = owner.insurance_status
            cached.cached_at = datetime.now(timezone.utc)
            cached.expires_at = expires
        else:
            new_cache = VehicleLookupCacheORM(
                vehicle_plate=plate,
                make=owner.make,
                model=owner.model,
                colour=owner.colour,
                year=owner.year,
                fuel_type=owner.fuel_type,
                tax_status=owner.tax_status,
                tax_due_date=owner.tax_due_date,
                mot_status=owner.mot_status,
                mot_expiry_date=owner.mot_expiry_date,
                keeper_name=owner.keeper_name,
                keeper_phone=owner.keeper_phone,
                insurance_status=owner.insurance_status,
                cached_at=datetime.now(timezone.utc),
                expires_at=expires,
            )
            session.add(new_cache)

    async def check_tax_and_mot(self, plate: str) -> dict[str, bool]:
        """
        Quick check if vehicle has valid tax and MOT.

        Returns dict with 'has_tax' and 'has_mot' booleans.
        Used by violation detection to flag untaxed/un-MOT'd vehicles.
        """
        owner = await self.lookup_vehicle(plate)
        return {
            "has_tax": owner.tax_status in ("Taxed", "SORN"),
            "has_mot": owner.mot_status in ("Valid", "No results returned"),
            "tax_status": owner.tax_status,
            "mot_status": owner.mot_status,
        }
