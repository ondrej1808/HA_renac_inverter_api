"""Select entities to read/write RENAC wallbox mode-style settings.

All backed by RenacSettingsCoordinator, derived from decompiled JS, not
a live capture -- see docs/API.md §2.10. Treat as higher-risk than the
read-only sensors until exercised against a real account.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import RenacApiError
from .const import (
    BASIC_CHARGE_AUTH_MODES,
    CHARGE_MODES,
    CONF_STATION_NAME,
    DOMAIN,
    EXTERNAL_CUR_SAMPLING_MODES,
    FAST_CHARGE_PLANS,
    PV_BOOST_MODES,
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

    entities: list[SelectEntity] = [RenacChargerModeSelect(coordinator, entry)]
    entities.extend(
        RenacSettingsSelect(settings, entry, desc) for desc in SELECT_DESCRIPTIONS
    )
    async_add_entities(entities)


class RenacChargerModeSelect(CoordinatorEntity[RenacWallboxCoordinator], SelectEntity):
    """Overall charging mode (fast/pv/off_peak): read from the realtime
    `api/charging/index` `mode` field, written via api/charging/set
    type=3. Replaces the old read-only `charge_mode` sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "charger_mode_select"

    def __init__(self, coordinator: RenacWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.inv_sn}_charger_mode_select"
        self._attr_options = [CHARGE_MODES[k] for k in sorted(CHARGE_MODES)]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.inv_sn)},
            name=entry.data.get(CONF_STATION_NAME, coordinator.inv_sn),
            manufacturer="RENAC",
            model="AC Wallbox",
            serial_number=coordinator.inv_sn,
        )

    @property
    def current_option(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return CHARGE_MODES.get(self.coordinator.data.get("mode"))

    async def async_select_option(self, option: str) -> None:
        raw = _enum_to_int(CHARGE_MODES, option)
        try:
            await self.coordinator.client.async_set_charger_mode(self.coordinator.inv_sn, raw)
        except RenacApiError:
            self.coordinator.logger.exception("Failed to set charger mode to %s", option)
            raise
        await self.coordinator.async_request_refresh()


@dataclass(frozen=True, kw_only=True)
class RenacSettingsSelectDescription(SelectEntityDescription):
    """A select backed by RenacSettingsCoordinator, written via
    RenacApiClient.async_set_charging(inv_sn, set_type, {field: value})."""

    group: str = ""
    field: str = ""
    set_type: int = 0
    enum: dict[int, str] | None = None
    value_fn: Callable[[dict[str, Any]], Any] = lambda data: None


def _enum_options(enum: dict[int, str]) -> list[str]:
    return [enum[k] for k in sorted(enum)]


def _enum_to_int(enum: dict[int, str], value: str) -> int:
    for k, v in enum.items():
        if v == value:
            return k
    raise ValueError(f"Unknown option {value!r}")


SELECT_DESCRIPTIONS: tuple[RenacSettingsSelectDescription, ...] = (
    RenacSettingsSelectDescription(
        key="basic_charge_auth_mode",
        translation_key="basic_charge_auth_mode",
        group="basic",
        field="charing_mode",
        set_type=2,
        enum=BASIC_CHARGE_AUTH_MODES,
        options=_enum_options(BASIC_CHARGE_AUTH_MODES),
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("charing_mode"),
    ),
    RenacSettingsSelectDescription(
        key="external_cur_sampling",
        translation_key="external_cur_sampling",
        group="basic",
        field="external_cur_sampling",
        set_type=2,
        enum=EXTERNAL_CUR_SAMPLING_MODES,
        options=_enum_options(EXTERNAL_CUR_SAMPLING_MODES),
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("external_cur_sampling"),
    ),
    RenacSettingsSelectDescription(
        key="pv_boost_mode",
        translation_key="pv_boost_mode",
        group="pv",
        field="boost",
        set_type=5,
        enum=PV_BOOST_MODES,
        options=_enum_options(PV_BOOST_MODES),
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("boost"),
    ),
    RenacSettingsSelectDescription(
        key="fast_charge_plan",
        translation_key="fast_charge_plan",
        group="fast",
        field="mode",
        set_type=4,
        enum=FAST_CHARGE_PLANS,
        options=_enum_options(FAST_CHARGE_PLANS),
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("mode"),
    ),
)


class RenacSettingsSelect(CoordinatorEntity[RenacSettingsCoordinator], SelectEntity):
    """A single settings-group enum field, read/write."""

    entity_description: RenacSettingsSelectDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RenacSettingsCoordinator,
        entry: ConfigEntry,
        description: RenacSettingsSelectDescription,
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
    def current_option(self) -> str | None:
        if not self.available:
            return None
        group = self.coordinator.data[self.entity_description.group]
        raw = self.entity_description.value_fn(group)
        if raw is None:
            return None
        return self.entity_description.enum.get(raw)

    async def async_select_option(self, option: str) -> None:
        desc = self.entity_description
        raw = _enum_to_int(desc.enum, option)
        try:
            await self.coordinator.client.async_set_charging(
                self.coordinator.inv_sn, desc.set_type, {desc.field: raw}
            )
        except RenacApiError:
            self.coordinator.logger.exception(
                "Failed to set %s to %s (type=%s)", desc.field, option, desc.set_type
            )
            raise
        await self.coordinator.async_request_refresh()
