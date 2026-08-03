"""Switch entities for RENAC wallbox boolean settings, plus charging on/off.

Most entities here are backed by RenacSettingsCoordinator, derived from
decompiled JS, not a live capture -- see docs/API.md §2.10. Treat those
as higher-risk than the read-only sensors until exercised against a
real account. `RenacChargingSwitch` (charging on/off) is the exception:
it was confirmed via a real HAR capture of the web portal's "turn on"/
"turn off charging" buttons and is backed by the realtime coordinator.

Both classes show the just-commanded state immediately (optimistic),
falling back to the real polled state once it confirms the command (or
after a timeout). Without this, the UI visibly "fights itself": right
after a click, the immediate post-command refresh -- and for the
settings switches, the next coordinator poll up to 5 minutes later --
would still show the pre-command value and the toggle would snap back
until the real device catches up.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
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

# How long an optimistic on/off guess is trusted before falling back to
# whatever the real polled state says, even if it never matched the
# command (e.g. "start" sent with no vehicle plugged in -- that's a
# legitimate outcome, not a stuck UI, so this must eventually give up).
_OPTIMISTIC_TIMEOUT_S = 120


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


class _OptimisticSwitchMixin:
    """Shared "show the commanded state until confirmed or timed out"
    behavior for both switch classes below."""

    _optimistic_is_on: bool | None = None
    _optimistic_timeout_unsub: Callable[[], None] | None = None

    def _resolve_is_on(self, actual: bool | None) -> bool | None:
        return self._optimistic_is_on if self._optimistic_is_on is not None else actual

    def _set_optimistic(self, value: bool) -> None:
        self._optimistic_is_on = value
        self._cancel_optimistic_timeout()
        self._optimistic_timeout_unsub = async_call_later(
            self.hass, _OPTIMISTIC_TIMEOUT_S, self._on_optimistic_timeout
        )
        self.async_write_ha_state()

    def _clear_optimistic(self) -> None:
        self._optimistic_is_on = None
        self._cancel_optimistic_timeout()

    def _cancel_optimistic_timeout(self) -> None:
        if self._optimistic_timeout_unsub is not None:
            self._optimistic_timeout_unsub()
            self._optimistic_timeout_unsub = None

    @callback
    def _on_optimistic_timeout(self, _now: Any) -> None:
        self._optimistic_timeout_unsub = None
        self._optimistic_is_on = None
        self.async_write_ha_state()

    def _confirm_or_keep_optimistic(self, actual: bool | None) -> None:
        """Call from _handle_coordinator_update with the freshly-polled
        real value: drops the optimistic override once it matches."""
        if self._optimistic_is_on is not None and actual == self._optimistic_is_on:
            self._clear_optimistic()


class RenacChargingSwitch(
    _OptimisticSwitchMixin, CoordinatorEntity[RenacWallboxCoordinator], SwitchEntity
):
    """Start/stop charging (api/charging/set type=3, `charger_cmd`).

    CONFIRMED live via a real HAR capture of the web portal's "turn on"/
    "turn off charging" buttons (2026-08-03) -- the only write action in
    this integration verified against a real network request rather
    than derived from decompiled JS. See docs/API.md §2.10.

    `is_on` reflects the wallbox's actual reported state (`state2` in
    {3, 6} = "charging") once confirmed -- e.g. it settles back to off
    if you send "start" but no vehicle is plugged in -- but shows the
    commanded state immediately after a click so the toggle doesn't
    visibly snap back while the physical hardware catches up.
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

    def _actual_is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("state2") in CHARGING_ACTIVE_STATES

    @property
    def is_on(self) -> bool | None:
        return self._resolve_is_on(self._actual_is_on())

    @callback
    def _handle_coordinator_update(self) -> None:
        self._confirm_or_keep_optimistic(self._actual_is_on())
        super()._handle_coordinator_update()

    async def _async_send(self, command: int, optimistic: bool) -> None:
        self._set_optimistic(optimistic)
        try:
            await self.coordinator.client.async_set_charger_command(
                self.coordinator.inv_sn, command
            )
        except RenacApiError:
            self._clear_optimistic()
            self.async_write_ha_state()
            self.coordinator.logger.exception("Failed to send charger_cmd=%s", command)
            raise
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_send(CHARGER_CMD_START, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send(CHARGER_CMD_STOP, False)


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


class RenacSettingsSwitch(
    _OptimisticSwitchMixin, CoordinatorEntity[RenacSettingsCoordinator], SwitchEntity
):
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

    def _actual_is_on(self) -> bool | None:
        if not self.available:
            return None
        group = self.coordinator.data[self.entity_description.group]
        raw = self.entity_description.value_fn(group)
        return None if raw is None else bool(int(raw))

    @property
    def is_on(self) -> bool | None:
        return self._resolve_is_on(self._actual_is_on())

    @callback
    def _handle_coordinator_update(self) -> None:
        self._confirm_or_keep_optimistic(self._actual_is_on())
        super()._handle_coordinator_update()

    async def _async_set(self, value: int) -> None:
        desc = self.entity_description
        self._set_optimistic(bool(value))
        try:
            await self.coordinator.client.async_set_charging(
                self.coordinator.inv_sn, desc.set_type, {desc.field: value}
            )
        except RenacApiError:
            self._clear_optimistic()
            self.async_write_ha_state()
            self.coordinator.logger.exception(
                "Failed to set %s to %s (type=%s)", desc.field, value, desc.set_type
            )
            raise
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(0)
