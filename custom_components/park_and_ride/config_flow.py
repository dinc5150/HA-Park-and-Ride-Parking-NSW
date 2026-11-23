"""Config and options flow for Park and Ride."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import ParkRideConfigEntry
from .api import (
    PORTAL_URL,
    CarPark,
    ParkRideApiError,
    ParkRideAuthError,
    ParkRideClient,
    ParkRideConnectionError,
)
from .const import (
    CONF_CAR_PARKS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)


def _label(car_park: CarPark) -> str:
    if car_park.address:
        return f"{car_park.short_name} ({car_park.address})"
    return car_park.short_name


KEY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


async def _fetch_car_parks(
    hass: HomeAssistant, api_key: str
) -> tuple[dict[str, CarPark] | None, str | None]:
    """Fetch the car park list with this key. Returns (car_parks, error_key)."""
    client = ParkRideClient(async_get_clientsession(hass), api_key)
    try:
        return await client.get_car_parks(), None
    except ParkRideAuthError:
        return None, "invalid_auth"
    except ParkRideConnectionError:
        return None, "cannot_connect"
    except ParkRideApiError:
        return None, "unexpected_response"


def _schema(
    car_parks: dict[str, CarPark],
    selected: list[str],
    interval: int,
) -> vol.Schema:
    """Build the form shared by the config flow and the options flow."""
    options = [
        SelectOptionDict(value=cp.id, label=_label(cp))
        for cp in sorted(car_parks.values(), key=lambda c: c.short_name.lower())
    ]
    # Keep previously chosen car parks selectable even if the feed dropped them.
    options.extend(
        SelectOptionDict(value=cp_id, label=f"Car park {cp_id} (not currently listed)")
        for cp_id in selected
        if cp_id not in car_parks
    )
    return vol.Schema(
        {
            vol.Required(CONF_CAR_PARKS, default=selected): SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_SCAN_INTERVAL, default=interval): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    unit_of_measurement="min",
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


class ParkRideConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_key = ""
        self._car_parks: dict[str, CarPark] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: the Open Data Hub API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            car_parks, error = await _fetch_car_parks(self.hass, api_key)
            if car_parks is not None:
                self._api_key, self._car_parks = api_key, car_parks
                return await self.async_step_car_parks()
            errors["base"] = error or "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=KEY_SCHEMA,
            errors=errors,
            description_placeholders={"portal_url": PORTAL_URL},
        )

    async def async_step_car_parks(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: which car parks to track."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_CAR_PARKS]:
                errors["base"] = "no_car_parks"
            else:
                return self.async_create_entry(
                    title="Park and Ride",
                    data={CONF_API_KEY: self._api_key},
                    options={
                        CONF_CAR_PARKS: user_input[CONF_CAR_PARKS],
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    },
                )

        return self.async_show_form(
            step_id="car_parks",
            data_schema=_schema(self._car_parks, [], DEFAULT_SCAN_INTERVAL),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key when the old one stops working."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            car_parks, error = await _fetch_car_parks(self.hass, api_key)
            if car_parks is not None:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_API_KEY: api_key}
                )
            errors["base"] = error or "unknown"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=KEY_SCHEMA,
            errors=errors,
            description_placeholders={"portal_url": PORTAL_URL},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ParkRideConfigEntry) -> OptionsFlow:
        return ParkRideOptionsFlow()


class ParkRideOptionsFlow(OptionsFlow):
    """Change the tracked car parks or polling interval later."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        car_parks, error = await _fetch_car_parks(
            self.hass, self.config_entry.data[CONF_API_KEY]
        )
        if car_parks is None:
            return self.async_abort(reason=error or "cannot_connect")

        if user_input is not None:
            if not user_input[CONF_CAR_PARKS]:
                errors["base"] = "no_car_parks"
            else:
                return self.async_create_entry(
                    data={
                        CONF_CAR_PARKS: user_input[CONF_CAR_PARKS],
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    }
                )

        current = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                car_parks,
                list(current.get(CONF_CAR_PARKS, [])),
                int(current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            ),
            errors=errors,
        )
