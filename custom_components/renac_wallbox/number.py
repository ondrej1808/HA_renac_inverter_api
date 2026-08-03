"""Number entity to set the RENAC wallbox's max output current.

Writes go through api/charging/set (type=2, ids="max_output_cur"), whose
payload shape was derived directly from the settings form component's
own decompiled JS (RenacApiClient.async_set_max_current / §2.10 in
docs/API.md) rather than from a live-captured network request. Treat
this entity as higher-risk than the read-only sensors until it has been
exercised against a real account.
"""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import RenacApiError
from .const import CONF_STATION_NAME, DOMAIN
from .coordinator import RenacWallboxCoordinator

_LOGGER = logging.getLogger(__name__)

# The web portal's own settings form doesn't declare a min/max for this
# field (it's a plain el-input-number with no bounds), so these are a
# conservative guess at typical single-phase/three-phase AC wallbox
# current limits, not a value confirmed from RENAC. Adjust if your
# hardware's real range differs.
MIN_CURRENT_A = 6
MAX_CURRENT_A = 32


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RenacWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RenacMaxCurrentNumber(coordinator, entry)])


class RenacMaxCurrentNumber(CoordinatorEntity[RenacWallboxCoordinator], NumberEntity):
    """Read/write the wallbox's configured max output current (A)."""

    _attr_has_entity_name = True
    _attr_translation_key = "max_current_setting"
    _attr_native_min_value = MIN_CURRENT_A
    _attr_native_max_value = MAX_CURRENT_A
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: RenacWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.inv_sn}_max_current_setting"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.inv_sn)},
            name=entry.data.get(CONF_STATION_NAME, coordinator.inv_sn),
            manufacturer="RENAC",
            model="AC Wallbox",
            serial_number=coordinator.inv_sn,
        )

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("max_cur")

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.client.async_set_max_current(
                self.coordinator.inv_sn, value
            )
        except RenacApiError:
            _LOGGER.exception("Failed to set max current to %s A", value)
            raise
        await self.coordinator.async_request_refresh()
