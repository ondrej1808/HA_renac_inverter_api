"""Config flow for the RENAC Wallbox integration.

Flow:
    1. user: base URL + email + password -> login.
    2. If the account has more than one wallbox station, let the user
       pick one (station_type == 8 stations only).
    3. Resolve the station's device serial (inv_sn). If a station has
       more than one device, let the user pick one.
    4. Create the config entry.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RenacApiClient, RenacApiError, RenacAuthError
from .const import (
    CONF_BASE_URL,
    CONF_INV_SN,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DEFAULT_BASE_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)


class RenacWallboxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RENAC Wallbox."""

    VERSION = 1

    def __init__(self) -> None:
        self._base_url: str | None = None
        self._email: str | None = None
        self._password: str | None = None
        self._client: RenacApiClient | None = None
        self._stations: list[dict[str, Any]] = []
        self._chosen_station: dict[str, Any] | None = None
        self._devices: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._base_url = user_input[CONF_BASE_URL]
            self._email = user_input["email"]
            self._password = user_input["password"]

            session = async_get_clientsession(self.hass)
            client = RenacApiClient(session, self._base_url, self._email, self._password)
            try:
                user_id = await client.async_login()
                stations = await client.async_get_wallbox_stations(user_id)
            except RenacAuthError:
                errors["base"] = "invalid_auth"
            except RenacApiError:
                errors["base"] = "cannot_connect"
            else:
                if not stations:
                    errors["base"] = "no_wallbox_stations"
                else:
                    self._client = client
                    self._stations = stations
                    if len(stations) == 1:
                        self._chosen_station = stations[0]
                        return await self.async_step_device()
                    return await self.async_step_station()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_station(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        options = {
            str(s["station_id"]): s.get("station_name", str(s["station_id"]))
            for s in self._stations
        }

        if user_input is not None:
            station_id = int(user_input["station_id"])
            self._chosen_station = next(
                s for s in self._stations if s["station_id"] == station_id
            )
            return await self.async_step_device()

        schema = vol.Schema({vol.Required("station_id"): vol.In(options)})
        return self.async_show_form(
            step_id="station", data_schema=schema, errors=errors
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        assert self._client is not None
        assert self._chosen_station is not None
        errors: dict[str, str] = {}
        station_id = self._chosen_station["station_id"]

        if not self._devices:
            try:
                self._devices = await self._client.async_get_station_devices(
                    self._client.user_id, station_id
                )
            except RenacApiError:
                errors["base"] = "cannot_connect"

        if not errors and len(self._devices) <= 1:
            inv_sn = (
                self._devices[0]["INV_SN"]
                if self._devices
                else self._chosen_station.get("equ_sn")
            )
            if not inv_sn:
                errors["base"] = "no_devices_found"
            else:
                return self._create_entry(inv_sn)

        if user_input is not None:
            return self._create_entry(user_input["inv_sn"])

        options = {d["INV_SN"]: d.get("INV_SN") for d in self._devices}
        schema = vol.Schema({vol.Required("inv_sn"): vol.In(options)})
        return self.async_show_form(
            step_id="device", data_schema=schema, errors=errors
        )

    def _create_entry(self, inv_sn: str) -> config_entries.FlowResult:
        assert self._chosen_station is not None
        station_name = self._chosen_station.get("station_name", inv_sn)
        return self.async_create_entry(
            title=f"RENAC Wallbox ({station_name})",
            data={
                CONF_BASE_URL: self._base_url,
                "email": self._email,
                "password": self._password,
                CONF_STATION_ID: self._chosen_station["station_id"],
                CONF_STATION_NAME: station_name,
                CONF_INV_SN: inv_sn,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return RenacWallboxOptionsFlow(config_entry)


class RenacWallboxOptionsFlow(config_entries.OptionsFlow):
    """Allow changing the poll interval after setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    "scan_interval_seconds",
                    default=self.config_entry.options.get("scan_interval_seconds", 30),
                ): vol.All(int, vol.Range(min=10, max=3600)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
