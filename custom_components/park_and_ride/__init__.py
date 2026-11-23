"""The Park and Ride (Transport NSW) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import ParkRideCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type ParkRideConfigEntry = ConfigEntry[ParkRideCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ParkRideConfigEntry) -> bool:
    """Set up Park and Ride from a config entry."""
    if not entry.data.get(CONF_API_KEY):
        # Entry created by v0.1.0, before an API key was needed.
        raise ConfigEntryAuthFailed("An API key is now required")

    coordinator = ParkRideCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _remove_deselected_devices(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ParkRideConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_options_change(
    hass: HomeAssistant, entry: ParkRideConfigEntry
) -> None:
    """Reload so a changed car park list or interval takes effect."""
    await hass.config_entries.async_reload(entry.entry_id)


def _remove_deselected_devices(
    hass: HomeAssistant, entry: ParkRideConfigEntry, coordinator: ParkRideCoordinator
) -> None:
    """Drop devices (and their entities) for car parks the user un-ticked."""
    selected = coordinator.selected_ids
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        ids = {ident[1] for ident in device.identifiers if ident[0] == DOMAIN}
        if ids and not ids & selected:
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )
