"""Sensors for the Energy Pebble integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import EnergyPebbleConfigEntry
from .const import COLOR_NAMES, CONF_DEVICE_ID, CONF_NICKNAME, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnergyPebbleConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the color sensor for the selected pebble."""
    async_add_entities([EnergyPebbleColorSensor(entry)])


class EnergyPebbleColorSensor(CoordinatorEntity, SensorEntity):
    """The pebble's current color: what the light on the wall shows."""

    _attr_has_entity_name = True
    _attr_name = "Color"
    _attr_icon = "mdi:circle-slice-8"
    _attr_options = ["green", "yellow", "red"]
    _attr_device_class = "enum"

    def __init__(self, entry: EnergyPebbleConfigEntry) -> None:
        super().__init__(entry.runtime_data)
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_color"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.data.get(CONF_NICKNAME, device_id),
            manufacturer="Energy Pebble",
            model="Energy Dot",
        )

    @property
    def native_value(self) -> str | None:
        codes = (self.coordinator.data or {}).get("hour_color_codes") or []
        if not codes:
            return None
        return COLOR_NAMES.get(codes[0].get("color_code"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        codes = data.get("hour_color_codes") or []
        meta = data.get("meta") or {}
        return {
            "current_hour": data.get("current_hour"),
            "next_hours": [
                {"hour": c.get("hour"), "color": COLOR_NAMES.get(c.get("color_code"))}
                for c in codes[1:]
            ],
            "signal_source": meta.get("signal_source"),
            "personalized": meta.get("personalized"),
            "display": data.get("display"),
        }
