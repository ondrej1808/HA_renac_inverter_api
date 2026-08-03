"""The RENAC Wallbox integration."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RenacApiClient
from .const import (
    CONF_BASE_URL,
    CONF_INV_SN,
    CONF_STATION_ID,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import RenacWallboxCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = RenacApiClient(
        session,
        entry.data[CONF_BASE_URL],
        entry.data["email"],
        entry.data["password"],
    )
    await client.async_login()

    coordinator = RenacWallboxCoordinator(
        hass,
        entry,
        client,
        inv_sn=entry.data[CONF_INV_SN],
        station_id=entry.data[CONF_STATION_ID],
    )
    scan_interval = entry.options.get("scan_interval_seconds")
    if scan_interval:
        coordinator.update_interval = timedelta(seconds=scan_interval)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
