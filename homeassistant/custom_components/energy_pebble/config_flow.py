"""Config flow for the Energy Pebble integration.

Step 1: sign in with the personal API token generated on the Energy Pebble
dashboard (user menu -> Settings -> Account). Step 2: pick which of your
claimed pebbles this Home Assistant entry follows.
"""
from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_TOKEN,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_NICKNAME,
    DEFAULT_HOST,
    DOMAIN,
)

TIMEOUT = aiohttp.ClientTimeout(total=15)


class EnergyPebbleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Energy Pebble config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str = DEFAULT_HOST
        self._token: str = ""
        self._user_id: str = ""
        self._devices: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Sign in: server address + personal API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST].rstrip("/")
            self._token = user_input[CONF_API_TOKEN].strip()
            session = async_get_clientsession(self.hass)
            headers = {"Authorization": f"Bearer {self._token}"}
            try:
                resp = await session.get(
                    f"{self._host}/api/ha/me", headers=headers, timeout=TIMEOUT
                )
                if resp.status == 200:
                    self._user_id = (await resp.json())["user_id"]
                    dev_resp = await session.get(
                        f"{self._host}/api/ha/devices", headers=headers, timeout=TIMEOUT
                    )
                    dev_resp.raise_for_status()
                    self._devices = (await dev_resp.json())["devices"]
                    if not self._devices:
                        errors["base"] = "no_devices"
                    else:
                        return await self.async_step_device()
                elif resp.status in (401, 403):
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=self._host): str,
                vol.Required(CONF_API_TOKEN): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_device(self, user_input: dict[str, Any] | None = None):
        """Pick which claimed pebble this entry follows."""
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            nickname = next(
                d["nickname"] for d in self._devices if d["device_id"] == device_id
            )
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Energy Pebble {nickname}",
                data={
                    CONF_HOST: self._host,
                    CONF_API_TOKEN: self._token,
                    CONF_DEVICE_ID: device_id,
                    CONF_NICKNAME: nickname,
                },
            )

        options = {d["device_id"]: d["nickname"] for d in self._devices}
        schema = vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(options)})
        return self.async_show_form(step_id="device", data_schema=schema)
