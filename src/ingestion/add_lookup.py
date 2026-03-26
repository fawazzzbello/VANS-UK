# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""
DVLA Access to Driver Data (ADD) API Integration.

Provides driver licence lookup for enforcement and notification purposes.
Used to enrich violation records with driver licence status, penalty points,
endorsements and disqualification data.

DVLA ADD API: https://developer-portal.driver-vehicle-licensing.api.gov.uk/
Authorisation required: organisations must be approved by DVLA for ADD access.

For simulation/demo: returns deterministic mock data derived from the VRN so
the same plate always produces the same "driver" without a live API key.
Set ADD_API_KEY env var to enable live API calls.
"""

import hashlib
import logging
import os
import random
import string
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ADD_API_BASE = "https://driver-vehicle-licensing.api.gov.uk/driver-enquiry/v1/drivers"

# Offence code catalogue (subset of DVLA codes used in endorsements)
_OFFENCE_CODES = [
    ("SP30", "Exceeding statutory speed limit on a public road", 3),
    ("SP50", "Exceeding speed limit on a motorway", 3),
    ("SP40", "Exceeding passenger vehicle speed limit", 3),
    ("CD10", "Driving without due care and attention", 3),
    ("IN10", "Using a vehicle uninsured against third-party risks", 6),
    ("TS10", "Failing to comply with traffic light signals", 3),
    ("CU80", "Using a mobile telephone while driving", 6),
    ("MW10", "Contravening a motorway regulation", 3),
    ("MS90", "Failure to give information as to identity of driver", 6),
    ("NE99", "Failure to notify DVLA of a notifiable disease or disability", 3),
]

_LICENCE_CATEGORIES = [
    ("B",   "Motor vehicles up to 3,500kg — standard car licence"),
    ("BE",  "Car with trailer combination"),
    ("A",   "Motorcycles (full category)"),
    ("A2",  "Motorcycles (restricted)"),
    ("C1",  "Vehicles between 3,500kg and 7,500kg"),
    ("C",   "Vehicles over 3,500kg (LGV/HGV)"),
    ("D1",  "Minibuses (up to 16 passengers)"),
    ("D",   "Buses/coaches"),
    ("AM",  "Mopeds and light quadricycles"),
]

_FORENAMES = ["James", "Oliver", "Harry", "George", "Noah", "Jack", "Charlie",
              "Alfie", "Freddie", "Oscar", "Emma", "Olivia", "Amelia", "Isla",
              "Ava", "Mia", "Isabella", "Sophie", "Lily", "Grace"]
_SURNAMES  = ["Smith", "Jones", "Williams", "Taylor", "Brown", "Davies", "Evans",
              "Wilson", "Thomas", "Roberts", "Johnson", "Lewis", "Walker", "Robinson",
              "Wood", "Thompson", "White", "Hughes", "Martin", "Clarke"]


@dataclass
class Endorsement:
    offence_code: str
    offence_description: str
    conviction_date: str       # ISO date
    sentence_date: str         # ISO date
    fine_pence: int
    disqualification_months: int
    points: int
    still_active: bool         # within 4-year counting period


@dataclass
class LicenceCategory:
    code: str
    description: str
    from_date: str
    to_date: str | None        # None = no expiry


@dataclass
class DriverData:
    vrn: str
    licence_number: str
    driver_name: str
    date_of_birth: str         # ISO date
    address: str
    licence_status: str        # FULL | PROVISIONAL | DISQUALIFIED | EXPIRED | REVOKED
    issue_date: str
    expiry_date: str
    photocard_number: str
    total_penalty_points: int
    is_disqualified: bool
    disqualified_until: str | None
    medical_restrictions: bool
    categories: list[LicenceCategory] = field(default_factory=list)
    endorsements: list[Endorsement] = field(default_factory=list)
    source: str = "MOCK"       # "ADD_API" when live


def _seeded(vrn: str) -> random.Random:
    """Return a seeded RNG so the same VRN always returns the same driver data."""
    seed = int(hashlib.sha256(vrn.upper().encode()).hexdigest(), 16) % (2**32)
    return random.Random(seed)


def _dvla_licence_number(rng: random.Random, surname: str, forename: str, dob: date) -> str:
    """Generate a realistic DVLA licence number from driver data."""
    sur = (surname.upper().ljust(5, "9"))[:5]
    decade = str(dob.year % 100).zfill(2)
    month  = str(dob.month).zfill(2)
    day    = str(dob.day).zfill(2)
    ini    = forename[0].upper()
    suffix = "".join(rng.choices(string.ascii_uppercase + string.digits, k=3))
    return f"{sur}{decade[0]}{month}{decade[1]}{day}{ini}9{suffix}"


def _mock_driver(vrn: str) -> DriverData:
    rng = _seeded(vrn)

    forename = rng.choice(_FORENAMES)
    surname  = rng.choice(_SURNAMES)
    name     = f"{forename} {surname}"

    # Date of birth — 18–75 years ago
    today    = date.today()
    dob      = today - timedelta(days=rng.randint(18 * 365, 75 * 365))
    dob_str  = dob.isoformat()

    # Licence
    issue    = today - timedelta(days=rng.randint(180, 20 * 365))
    expiry   = issue + timedelta(days=10 * 365)  # photocard valid 10 years
    lic_num  = _dvla_licence_number(rng, surname, forename, dob)
    photocard = "".join(rng.choices(string.digits, k=8))

    # Address (UK postcode format)
    streets   = ["High Street", "Church Lane", "Station Road", "Mill Lane", "The Green"]
    towns     = ["Manchester", "Birmingham", "Leeds", "Glasgow", "Bristol", "Liverpool", "Sheffield"]
    pc_area   = rng.choice(["M", "B", "LS", "G", "BS", "L", "S", "E", "W", "N", "SW"])
    pc_num    = f"{rng.randint(1,99)} {rng.randint(1,9)}{rng.choice(string.ascii_uppercase)}{rng.choice(string.ascii_uppercase)}"
    address   = f"{rng.randint(1,250)} {rng.choice(streets)}, {rng.choice(towns)}, {pc_area}{rng.randint(1,20)} {pc_num}"

    # Endorsements (0–4)
    num_endorsements = rng.choices([0, 1, 2, 3, 4], weights=[55, 25, 12, 5, 3])[0]
    endorsements = []
    total_points  = 0
    for _ in range(num_endorsements):
        code, desc, pts = rng.choice(_OFFENCE_CODES)
        conv_days_ago = rng.randint(30, 4 * 365)
        conv_date = today - timedelta(days=conv_days_ago)
        sent_date = conv_date + timedelta(days=rng.randint(14, 60))
        fine_p    = rng.choice([6500, 10000, 20000, 30000, 50000])
        disq_m    = rng.choice([0, 0, 0, 3, 6, 12]) if pts >= 6 else 0
        active    = conv_days_ago <= 4 * 365
        if active:
            total_points += pts
        endorsements.append(Endorsement(
            offence_code=code,
            offence_description=desc,
            conviction_date=conv_date.isoformat(),
            sentence_date=sent_date.isoformat(),
            fine_pence=fine_p,
            disqualification_months=disq_m,
            points=pts,
            still_active=active,
        ))

    # Disqualification
    is_disqualified = total_points >= 12
    disq_until = None
    if is_disqualified:
        disq_until = (today + timedelta(days=rng.randint(30, 365))).isoformat()

    # Licence status
    if expiry < today:
        status = "EXPIRED"
    elif is_disqualified:
        status = "DISQUALIFIED"
    elif dob + timedelta(days=17 * 365) > today:
        status = "PROVISIONAL"
    else:
        status = "FULL"

    # Categories (every driver has B; some have extras)
    all_cats = _LICENCE_CATEGORIES[:]
    rng.shuffle(all_cats)
    n_cats = rng.randint(1, 4)
    # Always include B
    chosen  = [c for c in all_cats if c[0] == "B"]
    for c in all_cats:
        if len(chosen) >= n_cats:
            break
        if c[0] != "B":
            chosen.append(c)

    categories = []
    for code, desc in chosen:
        cat_from = issue + timedelta(days=rng.randint(0, 365))
        cat_to   = None if code in ("B", "A") else (today + timedelta(days=rng.randint(365, 5 * 365))).isoformat()
        categories.append(LicenceCategory(
            code=code,
            description=desc,
            from_date=cat_from.isoformat(),
            to_date=cat_to,
        ))

    medical = rng.random() < 0.05  # 5% have medical restrictions

    return DriverData(
        vrn=vrn.upper(),
        licence_number=lic_num,
        driver_name=name,
        date_of_birth=dob_str,
        address=address,
        licence_status=status,
        issue_date=issue.isoformat(),
        expiry_date=expiry.isoformat(),
        photocard_number=photocard,
        total_penalty_points=total_points,
        is_disqualified=is_disqualified,
        disqualified_until=disq_until,
        medical_restrictions=medical,
        categories=categories,
        endorsements=endorsements,
        source="MOCK",
    )


class ADDLookupService:
    """
    DVLA Access to Driver Data service.

    Falls back to deterministic mock data when ADD_API_KEY is not set,
    enabling full demo operation without a live government API key.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ADD_API_KEY", "")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
            )
        return self._client

    async def lookup_driver(self, vrn: str) -> DriverData:
        """
        Return driver data for the registered keeper of the given VRN.

        Uses live ADD API when ADD_API_KEY is set; returns mock data otherwise.
        """
        vrn = vrn.upper().replace(" ", "").strip()

        if self.api_key:
            try:
                return await self._live_lookup(vrn)
            except Exception as e:
                logger.warning("ADD API call failed for %s: %s — falling back to mock", vrn, e)

        return _mock_driver(vrn)

    async def _live_lookup(self, vrn: str) -> DriverData:
        client = await self._get_client()
        resp   = await client.post(ADD_API_BASE, json={"registrationNumber": vrn})
        resp.raise_for_status()
        raw: dict[str, Any] = resp.json()

        endorsements = [
            Endorsement(
                offence_code=e.get("offenceCode", ""),
                offence_description=e.get("offenceDescription", ""),
                conviction_date=e.get("convictionDate", ""),
                sentence_date=e.get("sentenceDate", ""),
                fine_pence=int(e.get("fine", 0) * 100),
                disqualification_months=e.get("disqualificationMonths", 0),
                points=e.get("penaltyPoints", 0),
                still_active=e.get("stillActive", True),
            )
            for e in raw.get("endorsements", [])
        ]
        categories = [
            LicenceCategory(
                code=c.get("code", ""),
                description=c.get("description", ""),
                from_date=c.get("fromDate", ""),
                to_date=c.get("toDate"),
            )
            for c in raw.get("categories", [])
        ]

        return DriverData(
            vrn=vrn,
            licence_number=raw.get("licenceNumber", ""),
            driver_name=f"{raw.get('forename', '')} {raw.get('surname', '')}".strip(),
            date_of_birth=raw.get("dateOfBirth", ""),
            address=raw.get("address", ""),
            licence_status=raw.get("licenceStatus", "UNKNOWN"),
            issue_date=raw.get("issueDate", ""),
            expiry_date=raw.get("expiryDate", ""),
            photocard_number=raw.get("photocardNumber", ""),
            total_penalty_points=raw.get("totalPenaltyPoints", 0),
            is_disqualified=raw.get("isDisqualified", False),
            disqualified_until=raw.get("disqualifiedUntil"),
            medical_restrictions=raw.get("medicalRestrictions", False),
            categories=categories,
            endorsements=endorsements,
            source="ADD_API",
        )

    def driver_to_dict(self, d: DriverData) -> dict[str, Any]:
        """Serialise DriverData to a JSON-safe dict."""
        return {
            "vrn": d.vrn,
            "licence_number": d.licence_number,
            "driver_name": d.driver_name,
            "date_of_birth": d.date_of_birth,
            "address": d.address,
            "licence_status": d.licence_status,
            "issue_date": d.issue_date,
            "expiry_date": d.expiry_date,
            "photocard_number": d.photocard_number,
            "total_penalty_points": d.total_penalty_points,
            "is_disqualified": d.is_disqualified,
            "disqualified_until": d.disqualified_until,
            "medical_restrictions": d.medical_restrictions,
            "categories": [
                {"code": c.code, "description": c.description,
                 "from_date": c.from_date, "to_date": c.to_date}
                for c in d.categories
            ],
            "endorsements": [
                {"offence_code": e.offence_code, "offence_description": e.offence_description,
                 "conviction_date": e.conviction_date, "sentence_date": e.sentence_date,
                 "fine_pence": e.fine_pence, "disqualification_months": e.disqualification_months,
                 "points": e.points, "still_active": e.still_active}
                for e in d.endorsements
            ],
            "source": d.source,
        }
