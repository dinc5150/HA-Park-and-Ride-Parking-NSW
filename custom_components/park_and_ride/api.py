"""Client for the Transport for NSW Open Data Car Park API.

This module deliberately has no Home Assistant imports so it can be tested
(and reused) on its own.

Endpoint: GET https://api.transport.nsw.gov.au/v1/carpark/full-list
Auth:     Authorization: apikey <key>   (free key from the Open Data Hub)
Fields:   per the Car Park API documentation v2.2 (facility_id, facility_name,
          tsn, spots, occupancy.total, location, MessageDate).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_URL = "https://api.transport.nsw.gov.au/v1/carpark/full-list"
PORTAL_URL = "https://opendata.transport.nsw.gov.au"
PAGE_URL = (
    "https://transportnsw.info/travel-info/ways-to-get-around/drive/parking/"
    "transport-parkride-car-parks"
)
REQUEST_TIMEOUT = 20

# The documentation names these "Park&Ride – " (en dash); older feeds used a hyphen.
_NAME_PREFIX = re.compile(r"^Park&Ride\s*[-–—]\s*", re.IGNORECASE)
# MessageDate has no timezone in the feed; treated as Sydney local time.
FEED_TZ = ZoneInfo("Australia/Sydney")


class ParkRideError(Exception):
    """Base error for this client."""


class ParkRideConnectionError(ParkRideError):
    """The service could not be reached, was rate limited, or returned a bad status."""


class ParkRideAuthError(ParkRideError):
    """The API key was missing, invalid or not subscribed to the Car Park API."""


class ParkRideApiError(ParkRideError):
    """The service answered, but the payload was not what we expected."""


@dataclass(frozen=True, slots=True)
class CarPark:
    """A single Park&Ride car park and its latest reading."""

    id: str
    tsn: str | None
    name: str
    short_name: str
    capacity: int
    occupied: int | None  # None when the car park isn't reporting a count
    suburb: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    updated: datetime | None  # timezone-aware (Australia/Sydney)

    @property
    def available(self) -> int | None:
        """Free spaces (spots - occupancy.total), floored at 0.

        Transport NSW's recommended calculation. The feed can report more
        vehicles than spaces, hence the floor.
        """
        if self.occupied is None:
            return None
        return max(self.capacity - self.occupied, 0)

    @property
    def occupancy_percent(self) -> float | None:
        """Occupancy as a percentage, capped at 100."""
        if self.occupied is None or self.capacity <= 0:
            return None
        return round(min(self.occupied / self.capacity * 100, 100), 1)


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_one(item: Any) -> CarPark | None:
    """Parse one facility; return None if it is unusable."""
    if not isinstance(item, dict):
        return None
    try:
        car_park_id = str(item["facility_id"])
        name = str(item["facility_name"])
        capacity = int(float(item["spots"]))
    except (KeyError, TypeError, ValueError):
        _LOGGER.debug("Skipping unusable car park entry: %s", item)
        return None

    occupancy = item.get("occupancy")
    occupied = (
        _optional_int(occupancy.get("total")) if isinstance(occupancy, dict) else None
    )
    location = item.get("location")
    if not isinstance(location, dict):
        location = {}

    updated: datetime | None = None
    if raw_date := item.get("MessageDate") or item.get("messageDate"):
        try:
            updated = datetime.fromisoformat(raw_date).replace(tzinfo=FEED_TZ)
        except (TypeError, ValueError):
            updated = None

    tsn = item.get("tsn")
    return CarPark(
        id=car_park_id,
        tsn=str(tsn) if tsn is not None else None,
        name=name,
        short_name=_NAME_PREFIX.sub("", name),
        capacity=capacity,
        occupied=occupied,
        suburb=location.get("suburb"),
        address=location.get("address"),
        latitude=_optional_float(location.get("latitude")),
        longitude=_optional_float(location.get("longitude")),
        updated=updated,
    )


def _extract_items(payload: Any) -> list[Any]:
    """Find the list of facilities, whether bare or wrapped in an object."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "facility_id" in payload:  # a single facility
            return [payload]
        lists = [v for v in payload.values() if isinstance(v, list)]
        if len(lists) == 1:
            return lists[0]
        keys = ", ".join(sorted(payload)) or "none"
        raise ParkRideApiError(
            f"Could not find the car park list (top-level keys: {keys})"
        )
    raise ParkRideApiError(f"Unexpected response type: {type(payload).__name__}")


def parse_car_parks(payload: Any) -> dict[str, CarPark]:
    """Turn the API response into a dict keyed by facility id."""
    result: dict[str, CarPark] = {}
    for item in _extract_items(payload):
        if car_park := _parse_one(item):
            result[car_park.id] = car_park
    return result


def normalise_api_key(api_key: str) -> str:
    """Accept a bare key, or the whole 'apikey <key>' header value."""
    key = api_key.strip()
    if key.lower().startswith("apikey "):
        key = key[7:].strip()
    return key


class ParkRideClient:
    """Fetches all Park&Ride car parks in a single request."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = normalise_api_key(api_key)

    async def get_raw(self) -> Any:
        """Return the decoded JSON from the full-list endpoint."""
        headers = {
            "Accept": "application/json",
            "Authorization": f"apikey {self._api_key}",
        }
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(API_URL, headers=headers) as response:
                    if response.status in (401, 403):
                        raise ParkRideAuthError(
                            f"Transport NSW rejected the API key (HTTP {response.status})"
                        )
                    if response.status == 429:
                        raise ParkRideConnectionError(
                            "Rate limited by Transport NSW (HTTP 429)"
                        )
                    if response.status != 200:
                        raise ParkRideConnectionError(
                            f"Transport NSW returned HTTP {response.status}"
                        )
                    return await response.json(content_type=None)
        except TimeoutError as err:
            raise ParkRideConnectionError("Timed out talking to Transport NSW") from err
        except aiohttp.ClientError as err:
            raise ParkRideConnectionError(f"Connection error: {err}") from err
        except ValueError as err:  # JSON decode failure
            raise ParkRideApiError("Response was not valid JSON") from err

    async def get_car_parks(self) -> dict[str, CarPark]:
        """Return every car park currently in the feed, keyed by facility id."""
        return parse_car_parks(await self.get_raw())
