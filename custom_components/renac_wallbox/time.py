"""Time entities to read/write RENAC wallbox HH:mm schedule fields.

All backed by RenacSettingsCoordinator, derived from decompiled JS, not
a live capture -- see docs/API.md §2.10. Treat as higher-risk than the
read-only sensors until exercised against a real account.

Note: the fast-charge schedule's `*_begintime` fields use a special
sentinel value `"255:255"` (set by the "plug and charge immediately"
toggle in the web portal) that isn't a real time and can't be
represented by HA's TimeEntity -- reading one back shows as unset, and
writing through this entity always sends a real HH:mm value (never the
sentinel). Use the API client directly if you need to set that sentinel.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any, Callable

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import RenacApiError
from .const import CONF_STATION_NAME, DOMAIN
from .coordinator import RenacSettingsCoordinator

SENTINEL_NO_TIME = "255:255"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    settings: RenacSettingsCoordinator = hass.data[DOMAIN][entry.entry_id]["settings"]
    async_add_entities(
        RenacSettingsTime(settings, entry, desc) for desc in TIME_DESCRIPTIONS
    )


@dataclass(frozen=True, kw_only=True)
class RenacSettingsTimeDescription(TimeEntityDescription):
    """A time backed by RenacSettingsCoordinator, written via
    RenacApiClient.async_set_charging(inv_sn, set_type, {field: "HH:MM"})."""

    group: str = ""
    field: str = ""
    set_type: int = 0
    value_fn: Callable[[dict[str, Any]], Any] = lambda data: None


TIME_DESCRIPTIONS: tuple[RenacSettingsTimeDescription, ...] = (
    RenacSettingsTimeDescription(
        key="allow_charging_time_begin",
        translation_key="allow_charging_time_begin",
        group="basic",
        field="allow_charging_time_begin",
        set_type=2,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("allow_charging_time_begin"),
    ),
    RenacSettingsTimeDescription(
        key="allow_charging_time_end",
        translation_key="allow_charging_time_end",
        group="basic",
        field="allow_charging_time_end",
        set_type=2,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("allow_charging_time_end"),
    ),
    RenacSettingsTimeDescription(
        key="fast_time_begintime",
        translation_key="fast_time_begintime",
        group="fast",
        field="time_begintime",
        set_type=4,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("time_begintime"),
    ),
    RenacSettingsTimeDescription(
        key="fast_energy_begintime",
        translation_key="fast_energy_begintime",
        group="fast",
        field="energy_begintime",
        set_type=4,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("energy_begintime"),
    ),
    RenacSettingsTimeDescription(
        key="fast_cost_begintime",
        translation_key="fast_cost_begintime",
        group="fast",
        field="cost_begintime",
        set_type=4,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("cost_begintime"),
    ),
    RenacSettingsTimeDescription(
        key="pv_start_time",
        translation_key="pv_start_time",
        group="pv",
        field="start_time",
        set_type=5,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("start_time"),
    ),
    RenacSettingsTimeDescription(
        key="pv_stop_time",
        translation_key="pv_stop_time",
        group="pv",
        field="stop_time",
        set_type=5,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("stop_time"),
    ),
    RenacSettingsTimeDescription(
        key="pv_auto_time",
        translation_key="pv_auto_time",
        group="pv",
        field="auto_time",
        set_type=5,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("auto_time"),
    ),
    RenacSettingsTimeDescription(
        key="off_peak_auto_time",
        translation_key="off_peak_auto_time",
        group="off_peak",
        field="auto_time",
        set_type=6,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("auto_time"),
    ),
)


def _parse_hhmm(raw: Any) -> time | None:
    if not raw or raw == SENTINEL_NO_TIME:
        return None
    try:
        hh, mm = str(raw).split(":")
        return time(hour=int(hh), minute=int(mm))
    except (ValueError, TypeError):
        return None


class RenacSettingsTime(CoordinatorEntity[RenacSettingsCoordinator], TimeEntity):
    """A single settings-group HH:mm field, read/write."""

    entity_description: RenacSettingsTimeDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RenacSettingsCoordinator,
        entry: ConfigEntry,
        description: RenacSettingsTimeDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.inv_sn}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.inv_sn)},
            name=entry.data.get(CONF_STATION_NAME, coordinator.inv_sn),
            manufacturer="RENAC",
            model="AC Wallbox",
            serial_number=coordinator.inv_sn,
        )

    @property
    def available(self) -> bool:
        return bool(self.coordinator.data and self.entity_description.group in self.coordinator.data)

    @property
    def native_value(self) -> time | None:
        if not self.available:
            return None
        group = self.coordinator.data[self.entity_description.group]
        return _parse_hhmm(self.entity_description.value_fn(group))

    async def async_set_value(self, value: time) -> None:
        desc = self.entity_description
        formatted = f"{value.hour:02d}:{value.minute:02d}"
        try:
            await self.coordinator.client.async_set_charging(
                self.coordinator.inv_sn, desc.set_type, {desc.field: formatted}
            )
        except RenacApiError:
            self.coordinator.logger.exception(
                "Failed to set %s to %s (type=%s)", desc.field, formatted, desc.set_type
            )
            raise
        await self.coordinator.async_request_refresh()
