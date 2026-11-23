"""Config flow, setup, sensors and options flow."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.park_and_ride.api import (
    ParkRideApiError,
    ParkRideAuthError,
    ParkRideConnectionError,
)
from custom_components.park_and_ride.const import (
    CONF_CAR_PARKS,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import FEED


def _entry(car_parks: list[str], interval: int = 5) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Park and Ride",
        data={CONF_API_KEY: "test-key"},
        options={CONF_CAR_PARKS: car_parks, CONF_SCAN_INTERVAL: interval},
    )


async def _start_and_enter_key(hass: HomeAssistant, key: str = "  my-key "):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: key}
    )


async def test_config_flow_key_then_multiple_car_parks(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    result = await _start_and_enter_key(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "car_parks"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CAR_PARKS: ["486", "35"], CONF_SCAN_INTERVAL: 10},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: "my-key"}  # stripped
    assert result["options"] == {CONF_CAR_PARKS: ["486", "35"], CONF_SCAN_INTERVAL: 10}
    await hass.async_block_till_done()


async def test_config_flow_requires_at_least_one(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    result = await _start_and_enter_key(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CAR_PARKS: [], CONF_SCAN_INTERVAL: 5}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_car_parks"}


@pytest.mark.parametrize(
    ("exc", "error"),
    [
        (ParkRideAuthError("no"), "invalid_auth"),
        (ParkRideConnectionError("down"), "cannot_connect"),
        (ParkRideApiError("weird"), "unexpected_response"),
    ],
)
async def test_config_flow_key_errors_keep_form_open(
    hass: HomeAssistant, mock_feed: AsyncMock, exc: Exception, error: str
) -> None:
    mock_feed.side_effect = exc
    result = await _start_and_enter_key(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}

    # Fixing the key lets the user carry on.
    mock_feed.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "good"}
    )
    assert result["step_id"] == "car_parks"


async def test_reauth_updates_key_and_reloads(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    entry = _entry(["35"])
    entry.add_to_hass(hass)
    mock_feed.side_effect = ParkRideAuthError("revoked")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = list(hass.config_entries.flow.async_progress_by_handler(DOMAIN))
    assert [f["context"]["source"] for f in flows] == ["reauth"]

    mock_feed.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {CONF_API_KEY: "new-key"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data[CONF_API_KEY] == "new-key"
    assert entry.state is ConfigEntryState.LOADED


async def test_entry_without_key_from_v0_1_asks_for_reauth(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={CONF_CAR_PARKS: ["35"], CONF_SCAN_INTERVAL: 5}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert list(hass.config_entries.flow.async_progress_by_handler(DOMAIN))


async def test_only_one_config_entry_allowed(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    _entry(["486"]).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_sensors_created_per_car_park(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    entry = _entry(["486", "35"])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.ashfield_available_spaces").state == "0"
    assert hass.states.get("sensor.beverly_hills_available_spaces").state == "121"
    assert hass.states.get("sensor.beverly_hills_occupied_spaces").state == "79"
    assert hass.states.get("sensor.beverly_hills_capacity").state == "200"
    assert float(hass.states.get("sensor.beverly_hills_occupancy").state) == 39.5
    assert hass.states.get("sensor.beverly_hills_last_updated").state == (
        "2026-11-22T22:53:14+00:00"
    )
    # Not selected -> no entities
    assert hass.states.get("sensor.west_ryde_available_spaces") is None

    attrs = hass.states.get("sensor.beverly_hills_available_spaces").attributes
    assert attrs["address"] == "1 Test Street"
    assert attrs["capacity"] == 200

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert {d.name for d in devices} == {"Ashfield", "Beverly Hills"}


async def test_failed_poll_makes_entities_unavailable_then_recovers(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    entry = _entry(["35"])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.beverly_hills_available_spaces").state == "121"

    mock_feed.side_effect = ParkRideConnectionError("down")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.beverly_hills_available_spaces").state == (
        "unavailable"
    )

    mock_feed.side_effect = None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=12))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.beverly_hills_available_spaces").state == "121"


async def test_car_park_dropped_from_feed_is_unavailable(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    entry = _entry(["486", "35"])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    mock_feed.return_value = {k: v for k, v in FEED.items() if k != "486"}
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.ashfield_available_spaces").state == "unavailable"
    assert hass.states.get("sensor.beverly_hills_available_spaces").state == "121"


async def test_setup_retries_when_unreachable(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    mock_feed.side_effect = ParkRideConnectionError("down")
    entry = _entry(["35"])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_options_flow_changes_car_parks_and_removes_old_devices(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    entry = _entry(["486", "35"])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CAR_PARKS: ["35", "14"], CONF_SCAN_INTERVAL: 15}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[CONF_SCAN_INTERVAL] == 15
    assert hass.states.get("sensor.west_ryde_available_spaces").state == "51"
    assert hass.states.get("sensor.beverly_hills_available_spaces").state == "121"

    dev_reg = dr.async_get(hass)
    assert {
        d.name for d in dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    } == {
        "Beverly Hills",
        "West Ryde",
    }
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get("sensor.ashfield_available_spaces") is None


async def test_car_park_with_no_count_reports_unknown_not_full(
    hass: HomeAssistant, mock_feed: AsyncMock
) -> None:
    from dataclasses import replace

    mock_feed.return_value = {"35": replace(FEED["35"], occupied=None)}
    entry = _entry(["35"])
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.beverly_hills_available_spaces").state == "unknown"
    assert hass.states.get("sensor.beverly_hills_capacity").state == "200"
