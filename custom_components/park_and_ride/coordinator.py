"""Data update coordinator for Park and Ride."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CarPark, ParkRideAuthError, ParkRideClient, ParkRideError
from .const import CONF_CAR_PARKS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ParkRideCoordinator(DataUpdateCoordinator[dict[str, CarPark]]):
    """Polls the Transport NSW feed once and shares it with every sensor."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=minutes),
        )
        self.client = ParkRideClient(
            async_get_clientsession(hass), entry.data[CONF_API_KEY]
        )

    @property
    def selected_ids(self) -> set[str]:
        """Car park ids the user chose to track."""
        return set(self.config_entry.options.get(CONF_CAR_PARKS, []))

    async def _async_update_data(self) -> dict[str, CarPark]:
        try:
            all_car_parks = await self.client.get_car_parks()
        except ParkRideAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ParkRideError as err:
            raise UpdateFailed(str(err)) from err

        selected = self.selected_ids
        missing = selected - all_car_parks.keys()
        if missing:
            _LOGGER.debug("Selected car parks not in feed right now: %s", missing)
        return {k: v for k, v in all_car_parks.items() if k in selected}
