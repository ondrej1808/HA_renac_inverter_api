"""Switch entities to read/write RENAC wallbox boolean settings.

All backed by RenacSettingsCoordinator, derived from decompiled JS, not
a live capture -- see docs/API.md §2.10. Treat as higher-risk than the
read-only sensors until exercised against a real account.
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
from .const import CONF_STATION_NAME, DOMAIN
from .coordinator import RenacSettingsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    settings: RenacSettingsCoordinator = hass.data[DOMAIN][entry.entry_id]["settings"]
    async_add_entities(
        RenacSettingsSwitch(settings, entry, desc) for desc in SWITCH_DESCRIPTIONS
    )


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
