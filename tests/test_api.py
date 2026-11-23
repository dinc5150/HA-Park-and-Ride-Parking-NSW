"""Tests for the API client. Loads api.py directly so Home Assistant isn't needed.

Payload shapes follow the Transport NSW Car Park API documentation v2.2 (field
names facility_id, facility_name, tsn, spots, occupancy.total, location,
MessageDate). The live /full-list response is a bare list of those objects (see
the real captured sample at the bottom); wrapped shapes are still tolerated.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_API = Path(__file__).parent.parent / "custom_components" / "park_and_ride" / "api.py"
_spec = importlib.util.spec_from_file_location("pnr_api", _API)
api = importlib.util.module_from_spec(_spec)
sys.modules["pnr_api"] = api  # dataclasses needs the module registered
_spec.loader.exec_module(api)  # type: ignore[union-attr]


def _entry(**overrides):
    base = {
        "facility_id": "26",
        "facility_name": "Park&Ride – Tallawong P1",
        "tsn": "2155384",
        "tfnsw_facility_id": "2155384TPR001",
        "spots": "123",
        "ParkID": "1",
        "zones": [],
        "location": {
            "suburb": "Rouse Hill",
            "address": "Tallawong Road",
            "latitude": "-33.6942",
            "longitude": "150.9082",
        },
        "occupancy": {
            "loop": "5",
            "total": "100",
            "monthlies": "0",
            "open_gate": None,
            "transients": "0",
        },
        "MessageDate": "2024-11-25T11:08:35",
    }
    base.update(overrides)
    return base


def test_parses_documented_entry():
    cp = api.parse_car_parks([_entry()])["26"]
    assert cp.short_name == "Tallawong P1"
    assert cp.capacity == 123
    assert cp.occupied == 100
    assert cp.available == 23
    assert cp.tsn == "2155384"
    assert cp.address == "Tallawong Road"
    assert cp.latitude == pytest.approx(-33.6942)
    assert cp.updated.isoformat() == "2024-11-25T11:08:35+11:00"


def test_bare_list_and_wrapped_list_both_work():
    assert set(api.parse_car_parks([_entry()])) == {"26"}
    assert set(api.parse_car_parks({"carparks": [_entry()]})) == {"26"}
    assert set(api.parse_car_parks(_entry())) == {"26"}  # single facility


@pytest.mark.parametrize(
    ("name", "short"),
    [
        ("Park&Ride – Ashfield", "Ashfield"),  # en dash, as documented
        ("Park&Ride - Ashfield", "Ashfield"),  # plain hyphen
        ("Cherrybrook Station Car Park", "Cherrybrook Station Car Park"),
    ],
)
def test_name_prefix_stripped(name, short):
    assert api.parse_car_parks([_entry(facility_name=name)])["26"].short_name == short


def test_available_never_negative_when_over_capacity():
    cp = api.parse_car_parks([_entry(spots="228", occupancy={"total": "229"})])["26"]
    assert cp.available == 0
    assert cp.occupancy_percent == 100.0


def test_percent_normal():
    cp = api.parse_car_parks([_entry(spots="200", occupancy={"total": "79"})])["26"]
    assert cp.available == 121
    assert cp.occupancy_percent == 39.5


@pytest.mark.parametrize("occupancy", [None, {}, {"total": None}, {"total": ""}, "x"])
def test_missing_occupancy_total_means_unknown_not_full(occupancy):
    cp = api.parse_car_parks([_entry(occupancy=occupancy)])["26"]
    assert cp.occupied is None
    assert cp.available is None
    assert cp.occupancy_percent is None


def test_zero_capacity_has_no_percent():
    cp = api.parse_car_parks([_entry(spots="0", occupancy={"total": "0"})])["26"]
    assert cp.occupancy_percent is None


def test_unusable_entries_are_skipped_not_fatal():
    result = api.parse_car_parks(
        [
            _entry(facility_id="1"),
            _entry(facility_id="2", spots=None),
            _entry(facility_id="3", spots="many"),
            {"facility_name": "no id"},
            "garbage",
        ]
    )
    assert set(result) == {"1"}


def test_missing_location_and_bad_date_tolerated():
    cp = api.parse_car_parks([_entry(location=None, MessageDate="not a date")])["26"]
    assert cp.suburb is None and cp.latitude is None and cp.updated is None


@pytest.mark.parametrize(
    "bad",
    [None, "text", 5, {"message": "nope", "other": 1}, {"a": [], "b": []}],
)
def test_unrecognised_payloads_raise_api_error(bad):
    with pytest.raises(api.ParkRideApiError):
        api.parse_car_parks(bad)


def test_api_error_lists_top_level_keys_to_help_debugging():
    with pytest.raises(api.ParkRideApiError, match="message"):
        api.parse_car_parks({"message": "x", "other": 1})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("abc123", "abc123"),
        ("  abc123\n", "abc123"),
        ("apikey abc123", "abc123"),
        ("ApiKey   abc123", "abc123"),
    ],
)
def test_api_key_normalised(raw, expected):
    assert api.normalise_api_key(raw) == expected


class _FakeResponse:
    def __init__(self, status=200, payload=None, exc=None):
        self.status, self._payload, self._exc = status, payload, exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self, content_type=None):
        if self._exc:
            raise self._exc
        return self._payload


class _FakeSession:
    def __init__(self, response=None, raises=None):
        self._response, self._raises = response, raises
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append((url, headers))
        if self._raises:
            raise self._raises
        return self._response


async def test_client_sends_apikey_header_to_full_list():
    session = _FakeSession(_FakeResponse(payload=[_entry()]))
    result = await api.ParkRideClient(session, "  apikey SECRET ").get_car_parks()
    assert "26" in result
    url, headers = session.calls[0]
    assert url == "https://api.transport.nsw.gov.au/v1/carpark/full-list"
    assert headers["Authorization"] == "apikey SECRET"


@pytest.mark.parametrize("status", [401, 403])
async def test_client_bad_key_is_auth_error(status):
    session = _FakeSession(_FakeResponse(status=status))
    with pytest.raises(api.ParkRideAuthError):
        await api.ParkRideClient(session, "k").get_car_parks()


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_client_other_http_errors_are_connection_errors(status):
    session = _FakeSession(_FakeResponse(status=status))
    with pytest.raises(api.ParkRideConnectionError):
        await api.ParkRideClient(session, "k").get_car_parks()


async def test_client_network_error_is_connection_error():
    import aiohttp

    session = _FakeSession(raises=aiohttp.ClientConnectionError("down"))
    with pytest.raises(api.ParkRideConnectionError):
        await api.ParkRideClient(session, "k").get_car_parks()


async def test_client_invalid_json_is_api_error():
    session = _FakeSession(_FakeResponse(exc=ValueError("bad json")))
    with pytest.raises(api.ParkRideApiError):
        await api.ParkRideClient(session, "k").get_car_parks()


# --- Real response captured from /v1/carpark/full-list on 2026-11-23 -------------
# (first three car parks; the third was cut off in the capture before its
# tfnsw_facility_id, which the parser doesn't use.)

import json

_SAMPLE = json.loads(
    (Path(__file__).parent / "fixtures" / "full_list_sample.json").read_text()
)


def test_real_full_list_sample_parses():
    result = api.parse_car_parks(_SAMPLE)
    assert set(result) == {"486", "487", "488"}

    ashfield = result["486"]
    assert ashfield.short_name == "Ashfield"  # plain hyphen in the live feed
    assert (ashfield.capacity, ashfield.occupied, ashfield.available) == (228, 224, 4)
    assert ashfield.address == "Brown Street"
    assert ashfield.updated.isoformat() == "2026-11-23T14:36:19+11:00"

    assert result["487"].available == 13  # 259 - 246


def test_real_sample_uses_top_level_total_not_null_zone_totals():
    # Every zone reports total=null; only the top-level occupancy.total is set.
    seven_hills = api.parse_car_parks(_SAMPLE)["488"]
    assert seven_hills.capacity == 1613  # top-level spots (874 + 739 across zones)
    assert seven_hills.occupied == 875
    assert seven_hills.available == 738
