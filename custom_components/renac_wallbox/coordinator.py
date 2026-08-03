"""DataUpdateCoordinator polling one RENAC wallbox's realtime status."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RenacApiClient, RenacApiError, RenacAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, SETTINGS_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class RenacWallboxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls api/charging/index for a single inv_sn on an interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: RenacApiClient,
        inv_sn: str,
        station_id: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{inv_sn}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self.client = client
        self.inv_sn = inv_sn
        self.station_id = station_id

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if self.client.token is None:
                await self.client.async_login()
            status = await self.client.async_get_wallbox_status(self.inv_sn)
        except RenacAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except RenacApiError as err:
            raise UpdateFailed(f"Error talking to RENAC cloud: {err}") from err

        if not status:
            raise UpdateFailed("Empty status payload from api/charging/index")

        return status


class RenacSettingsCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Polls the wallbox's settings groups (api/charging/basic|fast|pv|off-peak).

    These endpoints are unconfirmed against a live account (derived from
    decompiled JS -- see docs/API.md §2.10), change far less often than
    realtime telemetry, and aren't essential to the integration's core
    read functionality -- so a failure on any one group is logged and
    that group is simply left out of `self.data`, rather than failing
    the whole coordinator (and therefore blocking config entry setup).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: RenacApiClient,
        inv_sn: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{inv_sn}_settings",
            update_interval=SETTINGS_SCAN_INTERVAL,
        )
        self.entry = entry
        self.client = client
        self.inv_sn = inv_sn

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        if self.client.token is None:
            try:
                await self.client.async_login()
            except RenacAuthError as err:
                raise UpdateFailed(f"Authentication failed: {err}") from err

        groups = {
            "basic": self.client.async_get_charging_basic,
            "fast": self.client.async_get_charging_fast,
            "pv": self.client.async_get_charging_pv,
            "off_peak": self.client.async_get_charging_off_peak,
        }
        data: dict[str, dict[str, Any]] = dict(self.data or {})
        for name, getter in groups.items():
            try:
                result = await getter(self.inv_sn)
            except RenacApiError as err:
                _LOGGER.warning("Could not fetch charging/%s settings: %s", name, err)
                continue
            if result:
                data[name] = result
        return data
