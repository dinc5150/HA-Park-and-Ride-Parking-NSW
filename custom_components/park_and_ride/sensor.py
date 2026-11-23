"""Sensors for Park and Ride."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ParkRideConfigEntry
from .api import PAGE_URL, CarPark
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import ParkRideCoordinator

PARALLEL_UPDATES = 0

UNIT_SPACES = "spaces"


@dataclass(frozen=True, kw_only=True)
class ParkRideSensorDescription(SensorEntityDescription):
    """Describes a Park and Ride sensor."""

    value_fn: Callable[[CarPark], StateType | datetime]


SENSORS: tuple[ParkRideSensorDescription, ...] = (
    ParkRideSensorDescription(
        key="available_spaces",
        translation_key="available_spaces",
        icon="mdi:car",
        native_unit_of_measurement=UNIT_SPACES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda cp: cp.available,
    ),
    ParkRideSensorDescription(
        key="occupied_spaces",
        translation_key="occupied_spaces",
        icon="mdi:car-multiple",
        native_unit_of_measurement=UNIT_SPACES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda cp: cp.occupied,
    ),
    ParkRideSensorDescription(
        key="occupancy",
        translation_key="occupancy",
        icon="mdi:gauge",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda cp: cp.occupancy_percent,
    ),
    ParkRideSensorDescription(
        key="capacity",
        translation_key="capacity",
        icon="mdi:parking",
        native_unit_of_measurement=UNIT_SPACES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda cp: cp.capacity,
    ),
    ParkRideSensorDescription(
        key="last_updated",
        translation_key="last_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda cp: cp.updated,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ParkRideConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensors for each selected car park, and for any that appear later."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_car_parks() -> None:
        new_ids = set(coordinator.data) - known
        if not new_ids:
            return
        known.update(new_ids)
        async_add_entities(
            ParkRideSensor(coordinator, car_park_id, description)
            for car_park_id in sorted(new_ids)
            for description in SENSORS
        )

    _add_new_car_parks()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_car_parks))


class ParkRideSensor(CoordinatorEntity[ParkRideCoordinator], SensorEntity):
    """A sensor for one reading of one car park."""

    _attr_has_entity_name = True
    entity_description: ParkRideSensorDescription

    def __init__(
        self,
        coordinator: ParkRideCoordinator,
        car_park_id: str,
        description: ParkRideSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._car_park_id = car_park_id
        car_park = coordinator.data[car_park_id]
        self._attr_unique_id = f"{car_park_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, car_park_id)},
            name=car_park.short_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=PAGE_URL,
        )

    @property
    def _car_park(self) -> CarPark | None:
        return self.coordinator.data.get(self._car_park_id)

    @property
    def available(self) -> bool:
        """Unavailable if the poll failed or the car park left the feed."""
        return super().available and self._car_park is not None

    @property
    def native_value(self) -> StateType | datetime:
        car_park = self._car_park
        return self.entity_description.value_fn(car_park) if car_park else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Static details, attached to the headline sensor only."""
        car_park = self._car_park
        if car_park is None or self.entity_description.key != "available_spaces":
            return None
        return {
            "car_park": car_park.name,
            "suburb": car_park.suburb,
            "address": car_park.address,
            "latitude": car_park.latitude,
            "longitude": car_park.longitude,
            "transport_stop_id": car_park.tsn,
            "capacity": car_park.capacity,
            "occupied": car_park.occupied,
            "facility_id": car_park.id,
        }
