"""Shared fixtures for the Home Assistant integration tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.park_and_ride.api import CarPark

pytest_plugins = "pytest_homeassistant_custom_component"

SYDNEY = ZoneInfo("Australia/Sydney")


def make_car_park(cp_id: str, name: str, capacity: int, occupied: int) -> CarPark:
    return CarPark(
        id=cp_id,
        tsn="1",
        name=f"Park&Ride - {name}",
        short_name=name,
        capacity=capacity,
        occupied=occupied,
        suburb=name,
        address="1 Test Street",
        latitude=-33.9,
        longitude=151.1,
        updated=datetime(2026, 11, 23, 9, 53, 14, tzinfo=SYDNEY),
    )


FEED = {
    "486": make_car_park("486", "Ashfield", 228, 229),
    "35": make_car_park("35", "Beverly Hills", 200, 79),
    "14": make_car_park("14", "West Ryde", 151, 100),
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow Home Assistant to load custom_components in tests."""


@pytest.fixture
def mock_feed() -> Generator[AsyncMock]:
    with patch(
        "custom_components.park_and_ride.api.ParkRideClient.get_car_parks",
        new_callable=AsyncMock,
        return_value=dict(FEED),
    ) as mock:
        yield mock
