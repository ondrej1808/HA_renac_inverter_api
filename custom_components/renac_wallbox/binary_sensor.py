"""Binary sensors derived from api/charging/index for a RENAC wallbox."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STATION_NAME, DOMAIN
from .coordinator import RenacWallboxCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RenacWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RenacFaultBinarySensor(coordinator, entry)])


class RenacFaultBinarySensor(CoordinatorEntity[RenacWallboxCoordinator], BinarySensorEntity):
    """On when the wallbox reports the fault state (state2 == 5)."""

    _attr_has_entity_name = True
    _attr_translation_key = "charger_fault"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: RenacWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.inv_sn}_fault"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.inv_sn)},
            name=entry.data.get(CONF_STATION_NAME, coordinator.inv_sn),
            manufacturer="RENAC",
            model="AC Wallbox",
            serial_number=coordinator.inv_sn,
        )

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("state2") == 5
