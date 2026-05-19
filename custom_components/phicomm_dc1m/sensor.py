"""Support for AirCat air quality sensors."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MACS, CONF_SENSOR_TYPES, DOMAIN, SENSOR_TYPES
from .coordinator import AirCatCoordinator
from . import AirCatConfigEntry

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS: dict[str, SensorEntityDescription] = {
    key: SensorEntityDescription(
        key=key,
        name=info["name"],
        native_unit_of_measurement={
            "µg/m³": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
            "mg/m³": CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER,
            "°C": UnitOfTemperature.CELSIUS,
            "%": PERCENTAGE,
        }.get(info["unit"]),
        icon=info["icon"],
        device_class=SensorDeviceClass(info["device_class"]),
        state_class=SensorStateClass(info["state_class"]),
    )
    for key, info in SENSOR_TYPES.items()
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AirCatConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AirCat sensor based on a config entry."""
    coordinator = entry.runtime_data
    macs: dict[str, str] = entry.data.get(CONF_MACS, {})
    sensors: list[str] = entry.data.get(CONF_SENSOR_TYPES, list(SENSOR_TYPES.keys()))

    entities: list[AirCatSensor] = []
    for idx, (mac, name) in enumerate(macs.items()):
        display_name = name if idx == 0 else f"{name} {idx + 1}"
        for sensor_type in sensors:
            if sensor_type in SENSOR_DESCRIPTIONS:
                entities.append(
                    AirCatSensor(coordinator, display_name, mac, sensor_type)
                )

    async_add_entities(entities)


class AirCatSensor(CoordinatorEntity[AirCatCoordinator], SensorEntity):
    """Representation of an AirCat sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AirCatCoordinator,
        name: str,
        mac: str,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._mac = mac
        self._sensor_type = sensor_type
        description = SENSOR_DESCRIPTIONS[sensor_type]
        self.entity_description = description

        self._attr_unique_id = f"aircat_{mac}_{sensor_type}"
        self._attr_translation_key = sensor_type
        self._attr_device_info = {
            "identifiers": {(DOMAIN, mac)},
            "name": name,
            "manufacturer": "AirCat",
            "model": "Air Quality Sensor",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.devs.get(self._mac) is not None

    @property
    def native_value(self) -> float | int | None:
        """Return the sensor value."""
        attributes = self.coordinator.devs.get(self._mac)
        if attributes is None:
            return None

        state = attributes.get(self._sensor_type)
        if state is None:
            return None

        try:
            if self._sensor_type == "value":  # PM2.5
                return int(state)
            elif self._sensor_type == "hcho":
                return round(float(state) / 1000, 3)
            else:
                return round(float(state), 1)
        except (ValueError, TypeError) as err:
            _LOGGER.error(
                "Error converting state for %s: %s (value: %s)",
                self.entity_id,
                err,
                state,
            )
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self._sensor_type != "value":
            return None
        return self.coordinator.devs.get(self._mac)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
