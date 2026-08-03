"""Switch entities for RENAC wallbox boolean settings, plus charging on/off.

Most entities here are backed by RenacSettingsCoordinator, derived from
decompiled JS, not a live capture -- see docs/API.md §2.10. Treat those
as higher-risk than the read-only sensors until exercised against a
real account. `RenacChargingSwitch` (charging on/off) is the exception:
it was confirmed via a real HAR capture of the web portal's "turn on"/
"turn off charging" buttons and is backed by the realtime coordinator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import RenacApiError
from .const import (
    CHARGER_CMD_START,
    CHARGER_CMD_STOP,
    CHARGING_ACTIVE_STATES,
    CONF_STATION_NAME,
    DOMAIN,
)
from .coordinator import RenacSettingsCoordinator, RenacWallboxCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: RenacWallboxCoordinator = entry_data["coordinator"]
    settings: RenacSettingsCoordinator = entry_data["settings"]

    entities: list[SwitchEntity] = [RenacChargingSwitch(coordinator, entry)]
    entities.extend(
        RenacSettingsSwitch(settings, entry, desc) for desc in SWITCH_DESCRIPTIONS
    )
    async_add_entities(entities)


class RenacChargingSwitch(CoordinatorEntity[RenacWallboxCoordinator], SwitchEntity):
    """Start/stop charging (api/charging/set type=3, `charger_cmd`).

    CONFIRMED live via a real HAR capture of the web portal's "turn on"/
    "turn off charging" buttons (2026-08-03) -- the only write action in
    this integration verified against a real network request rather
    than derived from decompiled JS. See docs/API.md §2.10.

    `is_on` reflects the wallbox's actual reported state (`state2` in
    {3, 6} = "charging"), not just the last command sent -- e.g. it
    stays off if you send "start" but no vehicle is plugged in.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "charging_switch"

    def __init__(self, coordinator: RenacWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.inv_sn}_charging_switch"
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
        return self.coordinator.data.get("state2") in CHARGING_ACTIVE_STATES

    async def _async_send(self, command: int) -> None:
        try:
            await self.coordinator.client.async_set_charger_command(
                self.coordinator.inv_sn, command
            )
        except RenacApiError:
            self.coordinator.logger.exception("Failed to send charger_cmd=%s", command)
            raise
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_send(CHARGER_CMD_START)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send(CHARGER_CMD_STOP)


@dataclass(frozen=True, kw_only=True)
class RenacSettingsSwitchDescription(SwitchEntityDescription):
    """A switch backed by RenacSettingsCoordinator, written via
    RenacApiClient.async_set_charging(inv_sn, set_type, {field: 0|1})."""

    group: str = ""
    field: str = ""
    set_type: int = 0
    value_fn: Callable[[dict[str, Any]], Any] = lambda data: None


SWITCH_DESCRIPTIONS: tuple[RenacSettingsSwitchDescription, ...] = (
    RenacSettingsSwitchDescription(
        key="pv_import_grid",
        translation_key="pv_import_grid",
        group="pv",
        field="import_grid",
        set_type=5,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("import_grid"),
    ),
    RenacSettingsSwitchDescription(
        key="off_peak_boost",
        translation_key="off_peak_boost",
        group="off_peak",
        field="boost",
        set_type=6,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("boost"),
    ),
    RenacSettingsSwitchDescription(
        key="load_balance_enabled",
        translation_key="load_balance_enabled",
        group="off_peak",
        field="balance",
        set_type=6,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("balance"),
    ),
)


class RenacSettingsSwitch(CoordinatorEntity[RenacSettingsCoordinator], SwitchEntity):
    """A single settings-group boolean field, read/write."""

    entity_description: RenacSettingsSwitchDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RenacSettingsCoordinator,
        entry: ConfigEntry,
        description: RenacSettingsSwitchDescription,
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
    def is_on(self) -> bool | None:
        if not self.available:
            return None
        group = self.coordinator.data[self.entity_description.group]
        raw = self.entity_description.value_fn(group)
        if raw is None:
            return None
        return bool(int(raw))

    async def _async_set(self, value: int) -> None:
        desc = self.entity_description
        try:
            await self.coordinator.client.async_set_charging(
                self.coordinator.inv_sn, desc.set_type, {desc.field: value}
            )
        except RenacApiError:
            self.coordinator.logger.exception(
                "Failed to set %s to %s (type=%s)", desc.field, value, desc.set_type
            )
            raise
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(0)
