"""Thin async client for the RENAC / seceu.renacpower.com cloud API.

The API is not publicly documented. Every endpoint and field name used
here was reverse engineered from the minified Vue.js web app served at
https://seceu.renacpower.com, cross-checked against a real captured
HTTP session (HAR) for a RENAC AC wallbox. See docs/API.md for the full
writeup of what is confirmed vs. inferred.

Auth scheme (confirmed from the axios request interceptor):
    - POST api/user/login with a plaintext JSON body
      {"login_name": <email>, "pwd": <password>} over HTTPS.
    - The response contains `user.token`, which must be sent on every
      subsequent request as three headers:
          Token: <token>
          timestamp: <unix seconds, integer>
          sign: md5(token + str(timestamp) + SIGN_SALT)
    - A `code`/`msg` envelope wraps every response. `code == 1` is
      success. `code == 400` is an error; `msg == "1000"` means the
      token is invalid/expired (re-login required), `msg == "1008"`
      means the client clock is skewed (data holds the offset in
      minutes) — the sign is time-based, so keep the host clock in sync.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import aiohttp

from .const import (
    CODE_ERROR,
    CODE_SUCCESS,
    MSG_TOKEN_INVALID,
    SIGN_SALT,
    STATION_TYPE_WALLBOX,
)

_LOGGER = logging.getLogger(__name__)


class RenacApiError(Exception):
    """Generic API error (non-zero `code`, HTTP error, network error)."""


class RenacAuthError(RenacApiError):
    """Raised when login fails or the token is rejected (msg == 1000)."""


class RenacApiClient:
    """Minimal client covering login + wallbox telemetry reads."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        email: str,
        password: str,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._token: str | None = None
        self._user_id: int | None = None

    @property
    def token(self) -> str | None:
        return self._token

    @property
    def user_id(self) -> int | None:
        return self._user_id

    def _sign_headers(self) -> dict[str, str]:
        if not self._token:
            raise RenacAuthError("Not logged in")
        timestamp = str(int(time.time()))
        raw = f"{self._token}{timestamp}{SIGN_SALT}"
        sign = hashlib.md5(raw.encode("utf-8")).hexdigest()
        return {"Token": self._token, "timestamp": timestamp, "sign": sign}

    async def _request(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        *,
        authed: bool = True,
        retry_on_auth_error: bool = True,
    ) -> Any:
        url = f"{self._base_url}/{path.lstrip('/')}"
        headers = {"Content-Type": "application/json;charset=utf-8"}
        if authed:
            headers.update(self._sign_headers())

        try:
            async with self._session.post(
                url, json=data or {}, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise RenacApiError(f"Network error calling {path}: {err}") from err

        _LOGGER.debug("POST %s data=%s -> %s", path, data, payload)

        code = payload.get("code")
        msg = payload.get("msg")

        if code == CODE_SUCCESS:
            return payload.get("data")

        if code == CODE_ERROR and msg == MSG_TOKEN_INVALID:
            if authed and retry_on_auth_error:
                _LOGGER.debug("Token rejected by %s, re-authenticating", path)
                await self.async_login()
                return await self._request(
                    path, data, authed=authed, retry_on_auth_error=False
                )
            raise RenacAuthError(f"Token rejected calling {path}: {payload}")

        raise RenacApiError(f"Unexpected response from {path}: {payload}")

    async def async_login(self) -> int:
        """Authenticate and store the session token.

        Confirmed request body: {"login_name": email, "pwd": password}
        (plaintext — the SPA does not hash or encrypt the password
        before sending it; the only protection is TLS).

        Confirmed response envelope: {"code": 1, "msg": "0000",
        "data": <numeric user_id>, "user": {"token": "...",
        "role_id": ..., "user_name": "..."}}.

        Returns the numeric user_id (required as a parameter on several
        other endpoints, e.g. api/station/list).
        """
        payload = {"login_name": self._email, "pwd": self._password}
        url = f"{self._base_url}/api/user/login"
        headers = {"Content-Type": "application/json;charset=utf-8"}
        try:
            async with self._session.post(
                url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                resp.raise_for_status()
                full = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise RenacApiError(f"Network error during login: {err}") from err

        if full.get("code") != CODE_SUCCESS:
            raise RenacAuthError(f"Login failed: {full}")

        user = full.get("user") or {}
        token = user.get("token")
        if not token:
            raise RenacAuthError(f"Login response missing token: {full}")
        self._token = token

        user_id = full.get("data")
        if not isinstance(user_id, int):
            raise RenacAuthError(f"Login response missing numeric user_id: {full}")
        self._user_id = user_id
        return user_id

    async def async_get_stations(self, user_id: int) -> list[dict[str, Any]]:
        """List stations owned by the account (api/station/list).

        Confirmed request body:
            {"user_id": <id>, "station_name": "", "status": null,
             "station_type": null, "offset": 0, "rows": 10,
             "installer_name": "", "user_name": "", "export_type": 0}
        Confirmed response: {"total": N, "list": [{station_id,
        station_name, station_type, equ_count, sum_energy, day_energy,
        status, ...}]}
        """
        payload = {
            "user_id": user_id,
            "station_name": "",
            "status": None,
            "station_type": None,
            "offset": 0,
            "rows": 100,
            "installer_name": "",
            "user_name": "",
            "export_type": 0,
        }
        data = await self._request("api/station/list", payload)
        return (data or {}).get("list", [])

    async def async_get_wallbox_stations(self, user_id: int) -> list[dict[str, Any]]:
        """Convenience wrapper: stations filtered to station_type == 8."""
        stations = await self.async_get_stations(user_id)
        return [s for s in stations if s.get("station_type") == STATION_TYPE_WALLBOX]

    async def async_get_station_devices(
        self, user_id: int, station_id: int
    ) -> list[dict[str, Any]]:
        """List the wallbox device(s) under a station (bg/equList).

        CONFIRMED live (2026-08-03): the SPA's `getPileIndex()` calls
        `d["n"]`, and static analysis of the minified charging-api module
        shows export "n" is bound to a helper posting to `bg/equList`
        (earlier revisions of this project incorrectly assumed this was
        `api/charging/index` with different params -- that guess was
        tested live and returns `{"code": 1, "data": null}`, i.e. no
        device list; `bg/equList` is the corrected endpoint).

        Request:  {"user_id": <id>, "station_id": <id>, "status": 0,
                   "offset": 0, "rows": 10}
        Response: {"total": N, "list": [{"INV_SN": "...", ...}]}
        """
        payload = {
            "user_id": user_id,
            "station_id": station_id,
            "status": 0,
            "offset": 0,
            "rows": 10,
        }
        data = await self._request("bg/equList", payload)
        return (data or {}).get("list", [])

    async def async_get_wallbox_status(self, inv_sn: str) -> dict[str, Any]:
        """Realtime status for one wallbox (api/charging/index).

        CONFIRMED via live HAR capture.
        Request: {"inv_sn": "<serial>"}
        Response (flattened, no list/total wrapper) includes:
            phase, mode, state, state2, max_cur, max_power, unit,
            unit_code, charger_cur, charger_vol, charger_power,
            charger_total_energy, charger_total_cost,
            charger_per_energy, charger_per_cost, charger_per_time,
            pv: {import_grid, min_solar_power, boost, manual_energy,
                 start_time, stop_time, auto_time, auto_energy,
                 last_operated_time}
        See docs/API.md for the full confirmed field reference and the
        state2 / mode enum meanings.
        """
        return await self._request("api/charging/index", {"inv_sn": inv_sn})

    async def async_get_charging_basic(self, inv_sn: str) -> dict[str, Any]:
        """Wallbox "basic settings" snapshot (api/charging/basic).

        Derived directly from the settings form component's `readBasic()`
        method (decompiled JS, not live-captured -- see docs/API.md §2.10
        for confidence level and full writeup).

        Request: {"inv_sn": "<serial>"}
        Response (`data`) includes at least: charing_mode (int, note the
        SPA's own typo -- not "charging_mode"), rfid, max_output_cur (A),
        protect_temp (°C), max_input_power, allow_charging_time_begin/
        _end, external_cur_sampling, meter_address, rate_number, and
        rate{N}_time_begin / rate{N}_time_end / rate{N}_rate for
        N in 1..rate_number (time-of-use tariff schedule).
        """
        return await self._request("api/charging/basic", {"inv_sn": inv_sn})

    async def async_get_charging_fast(self, inv_sn: str) -> dict[str, Any]:
        """Fast-charge schedule snapshot (api/charging/fast, confirmed path
        from the JS route table; payload derived from decompiled
        `readFast()` -- see docs/API.md §2.10).

        Request: {"inv_sn": "<serial>"}
        Response (`data`): {mode (0=time/1=energy/2=cost), time_number,
        time_begintime, time_day, energy_number, energy_begintime,
        energy_day, cost_number, cost_begintime, cost_day, inv_sn}.
        `*_begintime == "255:255"` means "charge immediately on plug-in"
        (no scheduled start) rather than a literal time.
        """
        return await self._request("api/charging/fast", {"inv_sn": inv_sn})

    async def async_get_charging_pv(self, inv_sn: str) -> dict[str, Any]:
        """PV/solar-boost charge settings snapshot (api/charging/pv,
        confirmed path; payload derived from decompiled `readPv()`).

        Request: {"inv_sn": "<serial>"}
        Response (`data`): {import_grid (0/1), min_solar_power (0-22000 W),
        boost (0=off/1=manual/2=intelligent), manual_energy, start_time,
        stop_time, auto_time, auto_energy, inv_sn}.
        """
        return await self._request("api/charging/pv", {"inv_sn": inv_sn})

    async def async_get_charging_off_peak(self, inv_sn: str) -> dict[str, Any]:
        """Off-peak schedule + load-balance settings snapshot
        (api/charging/off-peak, confirmed path; payload derived from
        decompiled `readOffPeak()`).

        Request: {"inv_sn": "<serial>"}
        Response (`data`): {boost (0/1), peak_time (comma-joined 0/1
        flags, one per configured tariff-rate slot from api/charging/basic
        §2.10), auto_time, auto_energy, balance (0/1), balance_power (W),
        inv_sn}.
        """
        return await self._request("api/charging/off-peak", {"inv_sn": inv_sn})

    async def async_set_charging(
        self, inv_sn: str, set_type: int, fields: dict[str, Any]
    ) -> None:
        """Write one or more fields via api/charging/set.

        Every write the wallbox settings form performs goes through this
        one endpoint, distinguished only by `type`. Derived directly from
        the settings form's `setMode(t)` method: it diffs the relevant
        form against the last-read snapshot and submits only the changed
        field names/values as parallel comma-joined lists. Confirmed
        field name for the current limit: `max_output_cur` (type 2).

        Request: {"equ_sn": "<serial>", "type": <int>,
                  "ids": "field_a,field_b", "params": "value_a,value_b"}
        Response: standard {"code": 1, ...} envelope; no meaningful data.

        `type` meanings, all derived from decompiled JS, NONE live-tested
        except type 2 / max_output_cur -- see docs/API.md §2.10 for the
        full writeup and per-field confidence notes:
            1 = RFID card (`rfid`)
            2 = basic settings (`charing_mode`, `max_output_cur`,
                `protect_temp`, `max_input_power`,
                `allow_charging_time_begin`/`_end`,
                `external_cur_sampling`, `meter_address`, tariff
                `rate{N}_time_begin`/`_end`/`_rate`)
            3 = overall charging mode switch (`charger_mode`: 0=fast,
                1=pv, 2=off_peak)
            4 = fast-charge schedule (`mode`, plus `time_number`/
                `time_begintime`/`time_day`, or `energy_number`/
                `energy_begintime`/`energy_day`, or `cost_number`/
                `cost_begintime`/`cost_day`, depending on `mode`)
            5 = PV/solar-boost settings (`import_grid`,
                `min_solar_power`, `boost`, plus `manual_energy`/
                `start_time`/`stop_time` when boost=1, or `auto_time`/
                `auto_energy` when boost=2)
            6 = off-peak schedule (`boost`, `peak_time`, `auto_time`,
                `auto_energy`) *and* load balancing (`balance`,
                `balance_power`) -- the SPA sends both under the same
                `type: 6`, distinguished only by which `ids` are given.

        The SPA always submits a full tab's worth of fields together
        (e.g. changing PV mode resends `import_grid`+`min_solar_power`+
        `boost` even if only one changed); this client instead sends
        exactly the field(s) you pass in `fields`, on the assumption
        (confirmed for type 1 / `rfid`, which the SPA itself always
        sends alone) that the API accepts partial field sets per `type`.
        Verify against your own account -- if a lone-field write for
        type 4/5/6 turns out to require its sibling fields too, pass
        them all explicitly.
        """
        def _fmt(value: Any) -> str:
            # Match how the SPA's own JS numbers serialize (16, not
            # 16.0) when a HA NumberEntity hands us a whole-number float.
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return str(value)

        payload = {
            "equ_sn": inv_sn,
            "type": set_type,
            "ids": ",".join(fields.keys()),
            "params": ",".join(_fmt(v) for v in fields.values()),
        }
        await self._request("api/charging/set", payload)

    async def async_set_charging_basic(
        self, inv_sn: str, fields: dict[str, Any]
    ) -> None:
        """Convenience wrapper: write "basic settings" fields (type=2)."""
        await self.async_set_charging(inv_sn, 2, fields)

    async def async_set_max_current(self, inv_sn: str, amps: float) -> None:
        """Convenience wrapper: set the wallbox's max output current (A)."""
        await self.async_set_charging_basic(inv_sn, {"max_output_cur": amps})

    async def async_set_charger_mode(self, inv_sn: str, mode: int) -> None:
        """Convenience wrapper: switch overall charging mode (type=3).

        `mode`: 0=fast, 1=pv, 2=off_peak (same enum as api/charging/index
        `mode` / const.CHARGE_MODES).
        """
        await self.async_set_charging(inv_sn, 3, {"charger_mode": mode})

    async def async_set_charger_command(self, inv_sn: str, command: int) -> None:
        """Start or stop charging (type=3, `charger_cmd`).

        CONFIRMED live: captured from a real "turn on"/"turn off charging"
        click in the web portal (HAR, 2026-08-03) -- the only write
        endpoint in this integration verified against a live network
        request rather than derived from decompiled JS. See docs/API.md
        §2.10 for the full writeup.

        `command`: 1 = start charging, 2 = stop charging.

        Note the real capture sends `"params": 1` as a JSON integer, not
        a string -- unlike every other `charging/set` write in this
        client (built by joining string lists), so this method bypasses
        `async_set_charging()`'s string formatting to match exactly.
        """
        payload = {"equ_sn": inv_sn, "type": 3, "ids": "charger_cmd", "params": command}
        await self._request("api/charging/set", payload)

    async def async_get_equip_stat(self, user_id: int, station_id: int) -> dict[str, Any]:
        """Online/offline/alarm device counts for a station (confirmed).

        Request: {"station_id": <id>, "user_id": <id>}
        Response: {"total_online_equip", "total_off_equip",
                   "total_alarm_equip", "total_equip"}
        """
        payload = {"station_id": station_id, "user_id": user_id}
        return await self._request("api/station/equipStat", payload)

    async def async_get_charging_records(
        self, inv_sn: str, begin_time: str, end_time: str, rows: int = 20
    ) -> dict[str, Any]:
        """Charging session history (confirmed via live HAR capture).

        Request: {"inv_sn": "<serial>", "begin_time": <ISO8601 or
        "yyyy-MM-dd">, "end_time": "yyyy-MM-dd", "offset": 0, "rows": N}
        Response: {"total": N, "results": [{begin_time, end_time,
        per_energy, per_cost, day_energy, day_cost, status, mark}, ...]}
        """
        payload = {
            "inv_sn": inv_sn,
            "begin_time": begin_time,
            "end_time": end_time,
            "offset": 0,
            "rows": rows,
        }
        data = await self._request("api/charging/equ/charging_record", payload)
        return data or {}
