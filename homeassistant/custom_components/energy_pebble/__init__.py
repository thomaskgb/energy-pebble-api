"""The Energy Pebble integration: color signal for your household's pebble."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_DEVICE_ID, CONF_HOST, DOMAIN, UPDATE_INTERVAL_MINUTES

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor"]
TIMEOUT = aiohttp.ClientTimeout(total=20)

type EnergyPebbleConfigEntry = ConfigEntry[DataUpdateCoordinator[dict[str, Any]]]


async def async_setup_entry(hass: HomeAssistant, entry: EnergyPebbleConfigEntry) -> bool:
    """Set up an Energy Pebble device from a config entry."""
    session = async_get_clientsession(hass)
    host = entry.data[CONF_HOST]
    device_id = entry.data[CONF_DEVICE_ID]

    async def _async_update() -> dict[str, Any]:
        # The color-code endpoint is public; sending the device id returns the
        # household-personalized signal for this pebble.
        try:
            resp = await session.get(
                f"{host}/api/color-code",
                headers={"X-Device-ID": device_id},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Energy Pebble API unreachable: {err}") from err

    coordinator: DataUpdateCoordinator[dict[str, Any]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{device_id}",
        update_method=_async_update,
        update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EnergyPebbleConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
