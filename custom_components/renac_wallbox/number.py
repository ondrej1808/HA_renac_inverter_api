"""Number entities to read/write RENAC wallbox settings.

`max_current_limit` writes through api/charging/set type=2 and is backed
by the realtime coordinator (api/charging/index already includes
max_cur, so it reflects a write faster than the slow settings poll).
Every other entity here is backed by RenacSettingsCoordinator
(api/charging/basic|fast|pv|off-peak) and was derived from decompiled
JS, not a live capture -- see docs/API.md §2.10 for the full writeup
and per-field confidence notes. Treat all of these as higher-risk than
the read-only sensors until exercised against a real account.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import RenacApiError
from .const import CONF_STATION_NAME, DOMAIN
from .coordinator import RenacSettingsCoordinator, RenacWallboxCoordinator

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
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: RenacWallboxCoordinator = entry_data["coordinator"]
    settings: RenacSettingsCoordinator = entry_data["settings"]

    entities: list[NumberEntity] = [
        RenacMaxCurrentNumber(coordinator, entry),
        RenacPollingIntervalNumber(coordinator, entry),
    ]
    entities.extend(
        RenacSettingsNumber(settings, entry, desc) for desc in SETTINGS_NUMBER_DESCRIPTIONS
    )
    async_add_entities(entities)


class RenacPollingIntervalNumber(CoordinatorEntity[RenacWallboxCoordinator], NumberEntity):
    """How often (seconds) the realtime coordinator polls api/charging/index.

    Purely a local Home Assistant setting -- never sent to the RENAC
    cloud. Equivalent to the integration's Configure (options flow)
    "Polling interval" field, exposed here as an entity so it's visible
    and adjustable directly from the device page. Takes effect from the
    next scheduled poll (HA's DataUpdateCoordinator re-reads
    `update_interval` each time it reschedules itself) and is persisted
    to the config entry's options so it survives a restart.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "polling_interval"
    _attr_native_min_value = 10
    _attr_native_max_value = 3600
    _attr_native_step = 10
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: RenacWallboxCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{coordinator.inv_sn}_polling_interval"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.inv_sn)},
            name=entry.data.get(CONF_STATION_NAME, coordinator.inv_sn),
            manufacturer="RENAC",
            model="AC Wallbox",
            serial_number=coordinator.inv_sn,
        )

    @property
    def native_value(self) -> float:
        return self.coordinator.update_interval.total_seconds()

    async def async_set_native_value(self, value: float) -> None:
        seconds = int(value)
        self.coordinator.update_interval = timedelta(seconds=seconds)
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, "scan_interval_seconds": seconds}
        )
        self.async_write_ha_state()


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
            self.coordinator.logger.exception("Failed to set max current to %s A", value)
            raise
        await self.coordinator.async_request_refresh()


@dataclass(frozen=True, kw_only=True)
class RenacSettingsNumberDescription(NumberEntityDescription):
    """A number backed by RenacSettingsCoordinator, written via
    RenacApiClient.async_set_charging(inv_sn, set_type, {field: value})."""

    group: str = ""
    field: str = ""
    set_type: int = 0
    value_fn: Callable[[dict[str, Any]], Any] = lambda data: None


SETTINGS_NUMBER_DESCRIPTIONS: tuple[RenacSettingsNumberDescription, ...] = (
    RenacSettingsNumberDescription(
        key="protect_temp",
        translation_key="protect_temp",
        group="basic",
        field="protect_temp",
        set_type=2,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=0,
        native_max_value=120,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("protect_temp"),
    ),
    RenacSettingsNumberDescription(
        key="meter_address",
        translation_key="meter_address",
        group="basic",
        field="meter_address",
        set_type=2,
        native_min_value=0,
        native_max_value=255,
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("meter_address"),
    ),
    RenacSettingsNumberDescription(
        key="pv_min_solar_power",
        translation_key="pv_min_solar_power_setting",
        group="pv",
        field="min_solar_power",
        set_type=5,
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=22000,
        native_step=100,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("min_solar_power"),
    ),
    RenacSettingsNumberDescription(
        key="pv_manual_energy",
        translation_key="pv_manual_energy",
        group="pv",
        field="manual_energy",
        set_type=5,
        native_unit_of_measurement="kWh",
        native_min_value=0,
        native_max_value=200,
        native_step=0.1,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("manual_energy"),
    ),
    RenacSettingsNumberDescription(
        key="pv_auto_energy",
        translation_key="pv_auto_energy",
        group="pv",
        field="auto_energy",
        set_type=5,
        native_unit_of_measurement="kWh",
        native_min_value=0,
        native_max_value=200,
        native_step=0.1,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("auto_energy"),
    ),
    RenacSettingsNumberDescription(
        key="off_peak_auto_energy",
        translation_key="off_peak_auto_energy",
        group="off_peak",
        field="auto_energy",
        set_type=6,
        native_unit_of_measurement="kWh",
        native_min_value=0,
        native_max_value=200,
        native_step=0.1,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("auto_energy"),
    ),
    RenacSettingsNumberDescription(
        key="balance_power",
        translation_key="balance_power",
        group="off_peak",
        field="balance_power",
        set_type=6,
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=0,
        native_max_value=22000,
        native_step=100,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("balance_power"),
    ),
    RenacSettingsNumberDescription(
        key="fast_preset_energy",
        translation_key="fast_preset_energy",
        group="fast",
        field="energy_number",
        set_type=4,
        native_unit_of_measurement="kWh",
        native_min_value=0,
        native_max_value=200,
        native_step=0.1,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("energy_number"),
    ),
    RenacSettingsNumberDescription(
        key="fast_preset_cost",
        translation_key="fast_preset_cost",
        group="fast",
        field="cost_number",
        set_type=4,
        native_min_value=0,
        native_max_value=100000,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data: data.get("cost_number"),
    ),
)


class RenacSettingsNumber(CoordinatorEntity[RenacSettingsCoordinator], NumberEntity):
    """A single settings-group numeric field, read/write."""

    entity_description: RenacSettingsNumberDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RenacSettingsCoordinator,
        entry: ConfigEntry,
        description: RenacSettingsNumberDescription,
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
    def native_value(self) -> Any:
        if not self.available:
            return None
        group = self.coordinator.data[self.entity_description.group]
        return self.entity_description.value_fn(group)

    async def async_set_native_value(self, value: float) -> None:
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
