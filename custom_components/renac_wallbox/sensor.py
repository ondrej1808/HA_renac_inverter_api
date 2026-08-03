"""Sensor entities for a RENAC wallbox, backed by api/charging/index."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CHARGE_MODES, CHARGE_PHASES, CHARGE_STATES, CONF_STATION_NAME, DOMAIN
from .coordinator import RenacWallboxCoordinator


@dataclass(frozen=True, kw_only=True)
class RenacSensorDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with a value getter."""

    value_fn: Callable[[dict[str, Any]], Any] = lambda data: None


SENSOR_DESCRIPTIONS: tuple[RenacSensorDescription, ...] = (
    RenacSensorDescription(
        key="charger_power",
        translation_key="charger_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("charger_power"),
    ),
    RenacSensorDescription(
        key="charger_vol",
        translation_key="charger_vol",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("charger_vol"),
    ),
    RenacSensorDescription(
        key="charger_cur",
        translation_key="charger_cur",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("charger_cur"),
    ),
    RenacSensorDescription(
        key="charger_total_energy",
        translation_key="charger_total_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.get("charger_total_energy"),
    ),
    RenacSensorDescription(
        key="charger_per_energy",
        translation_key="charger_per_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        # No state_class: this is a per-session value that resets to 0 at
        # the start of every charge, so neither "measurement" (disallowed
        # by HA for device_class energy) nor "total_increasing" (would
        # misread the reset as a meter rollback) fit.
        value_fn=lambda data: data.get("charger_per_energy"),
    ),
    RenacSensorDescription(
        key="charger_total_cost",
        translation_key="charger_total_cost",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.get("charger_total_cost"),
    ),
    RenacSensorDescription(
        key="charger_per_cost",
        translation_key="charger_per_cost",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("charger_per_cost"),
    ),
    RenacSensorDescription(
        key="charger_per_time",
        translation_key="charger_per_time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda data: data.get("charger_per_time"),
    ),
    RenacSensorDescription(
        key="state",
        translation_key="charge_state",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(set(CHARGE_STATES.values())),
        value_fn=lambda data: CHARGE_STATES.get(data.get("state2")),
    ),
    RenacSensorDescription(
        key="mode",
        translation_key="charge_mode",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(set(CHARGE_MODES.values())),
        value_fn=lambda data: CHARGE_MODES.get(data.get("mode")),
    ),
    RenacSensorDescription(
        key="phase",
        translation_key="charge_phase",
        device_class=SensorDeviceClass.ENUM,
        options=sorted(set(CHARGE_PHASES.values())),
        value_fn=lambda data: CHARGE_PHASES.get(data.get("phase")),
    ),
    # max_cur is intentionally not exposed as a sensor: it's now a
    # writable `number.*_max_current_setting` entity (see number.py),
    # which also displays the current value.
    RenacSensorDescription(
        key="max_power",
        translation_key="max_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.get("max_power"),
    ),
    RenacSensorDescription(
        key="pv_min_solar_power",
        translation_key="pv_min_solar_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (data.get("pv") or {}).get("min_solar_power"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RenacWallboxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RenacSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class RenacSensor(CoordinatorEntity[RenacWallboxCoordinator], SensorEntity):
    """A single telemetry value read from api/charging/index."""

    entity_description: RenacSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RenacWallboxCoordinator,
        entry: ConfigEntry,
        description: RenacSensorDescription,
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
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.key in ("charger_total_cost", "charger_per_cost"):
            unit_code = (self.coordinator.data or {}).get("unit_code")
            if unit_code:
                return unit_code
        return self.entity_description.native_unit_of_measurement
