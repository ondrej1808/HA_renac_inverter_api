"""DataUpdateCoordinator polling one RENAC wallbox's realtime status."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RenacApiClient, RenacApiError, RenacAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

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
