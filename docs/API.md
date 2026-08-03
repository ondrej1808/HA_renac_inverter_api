# RENAC Wallbox — API Reference & Technical Notes

Full reverse-engineered documentation of the RENAC cloud API used by [`custom_components/renac_wallbox/`](../custom_components/renac_wallbox/). If you just want to install and use the integration, see the main [README](../README.md) instead — this document is for anyone extending the code, verifying a claim, or picking up unfinished work (a coding agent or a human).

> 🇨🇿 Česká verze je níže. / 🇬🇧 English version first, Czech version below.

---

## 1. Status

> ✅ **Successfully tested end-to-end on a real RENAC EV-AC3P-11K wallbox** — login, station/device auto-discovery, and live sensor readings (power, voltage, current, energy, cost, state, mode) all confirmed working through the full HACS install flow inside a real Home Assistant instance.

| Piece | Status |
|---|---|
| Auth (login, token signing) | ✅ Confirmed against a live account |
| `api/station/list` | ✅ Confirmed (live capture) |
| `api/charging/index` (single device, `{inv_sn}`) | ✅ Confirmed (live capture) — **this is the "read all wallbox data" call** |
| `bg/equList` (device discovery per station) | ✅ Confirmed against a live account (an earlier guess of `api/charging/index` with different params was tested live and found wrong — see §2.5) |
| `api/station/equipStat` | ✅ Confirmed (live capture) |
| `api/charging/equ/charging_record` (session history) | ✅ Confirmed (live capture) |
| `api/charging/equ/detailChart` (time-series history) | ✅ Confirmed (live capture) |
| `api/charging/basic\|fast\|pv\|off-peak` (read settings) | ⚠️ Derived from decompiled JS (exact request-building code, not a guessed shape), not live-captured — see §2.10 |
| `api/charging/set` all 6 `type` values (write settings, incl. max current) | ⚠️ 24 entities implemented across `number`/`select`/`switch`/`time`, derived from decompiled JS, tested against the Docker mock server (full read/write round trip, no errors) but not yet a real account — see §2.10 |
| `api/charging/set` type=3, `charger_cmd` (start/stop charging) | ✅ Confirmed live — captured from a real "turn on"/"turn off charging" click in the web portal, the only write action verified against a live network request in this project. `switch.*_charging` — see §2.11 |
| Home Assistant integration (`custom_components/renac_wallbox/`) | ✅ Read path tested end-to-end against a real RENAC EV-AC3P-11K wallbox via the full HACS install flow; the settings write path (24 entities) is Docker-mock-tested only; the start/stop `charger_cmd` write is confirmed live (see §5) |
| Regions other than Europe | ⚠️ Base URL pattern guessed, unverified |

**How this was reverse engineered:** the RENAC web portal is a Vue.js SPA. Its production JS bundles (`app.*.js` + chunk files) were fetched and searched directly (no login required to read the client code) for API route strings, the axios request/response interceptors, and the login form logic. This gave the auth scheme and most endpoint paths/params. A **HAR capture of a real authenticated browser session against a real wallbox** was then used to confirm exact request/response JSON shapes for the endpoints marked ✅ above. **All identifying values from that capture (token, user id, device serial, station id, station name, owner name, installer name) were replaced with fake placeholders before anything was written to this repository** — only the field *names* and realistic *shapes/value types* are real. The token itself was never written to disk outside the original local HAR file, and is not present anywhere in this repository or its history.

**Prior art / cross-checked against:**
- The official **"RENAC SEC API Documentation" v2.0.7** (a partner/open-platform PDF circulated on the [ioBroker forum](https://forum.iobroker.net/)) independently documents `api/user/login` and `api/station/list` with the exact same parameter and response-field names found here — this confirms those two endpoints rather than relying on the JS reverse-engineering alone. That document targets a different default host (`153.le-pv.com:8082`, no HTTPS, no signing headers) and **does not mention any wallbox/EV-charging endpoint, nor the `Token`/`timestamp`/`sign` header scheme** used by the production web portal — the charging-pile endpoints and the request-signing scheme documented in §2 below are original findings from this project, not copied from that document.
- [`raschy/ioBroker.renacidc`](https://github.com/raschy/ioBroker.renacidc), an independent ioBroker adapter for RENAC *solar inverters* (not wallboxes), lists a changelog entry for a "special API signature" it had to reverse-engineer on its own — corroborating that the RENAC cloud does require custom request signing beyond what the official PDF documents, without that project's source being consulted or copied here.
- [`gastush/ha-renac`](https://github.com/gastush/ha-renac) and [`HA1Andrzej/RENAC-MODBUS`](https://github.com/HA1Andrzej/RENAC-MODBUS) are existing Home Assistant integrations for RENAC **hybrid/on-grid solar inverters** over local Modbus/RS485 — a completely different transport (LAN, not cloud) and product line from the AC wallbox covered here. No overlap in code or endpoints.

---

## 2. Confirmed API contract

Base URL (Europe region, confirmed): `https://europe.renacpower.com:8084/`
It is read at runtime by the web app from a global `window.baseUrl.path` set outside the JS bundle — other regions (Asia, South America were seen as UI options) presumably use `https://<region>.renacpower.com:8084/`, but **this has not been verified**. Treat the base URL as configurable, not hardcoded.

Note: the official partner API PDF (see prior-art note above) documents a *different* default host, `http://153.le-pv.com:8082` (plain HTTP, no auth-signing headers), for the same `api/user/login` / `api/station/list` endpoints. This is presumably an older or global fallback deployment; the wallbox/EV-charging endpoints and the `Token`/`timestamp`/`sign` signing requirement were only observed on the region-specific `europe.renacpower.com:8084` host used by the current web portal, so that is what this integration targets by default.

### 2.1 Auth & request signing (confirmed)

Every request (except `login`, `register`, `getWebVer`, `sendEmailCode`, `forgetpwd`, `alertRenac`) must carry three headers derived from the session token:

```
Token: <token from login>
timestamp: <current unix time in seconds, as a string>
sign: MD5(token + str(timestamp) + "9P@3kF7sD2&zX5cV8bNm1qR4tY6uI0o")
```

The salt string above is hardcoded in the client JS (not a per-user secret) — it was extracted verbatim from the request interceptor. `sign` is lowercase hex MD5. Content-Type for POST bodies is `application/json;charset=utf-8`. All calls are `POST`, even ones that are logically "reads".

Response envelope for every endpoint:

```json
{ "code": 1, "msg": "0000", "data": { /* payload, shape varies per endpoint */ } }
```

* `code == 1` → success, use `data`.
* `code == 400` and `msg == "1000"` → token invalid/expired → **re-login** (`api/user/login`) and retry once.
* `code == 400` and `msg == "1008"` → client clock is skewed; `data` holds the offset in minutes. Because `sign` is time-based, keep the host clock in sync (NTP) or the API will reject every signed request.

### 2.2 `POST api/user/login` (confirmed)

Request:
```json
{ "login_name": "you@example.com", "pwd": "your-password" }
```
The password is sent **in plaintext** — the SPA does not hash or encrypt it client-side. The only protection is TLS. There is a demo account visible in the JS (`888@qq.com` / `123456`) used for the portal's own "try demo" button.

Response:
```json
{
  "code": 1,
  "msg": "0000",
  "data": 100001,
  "user": { "token": "...", "role_id": 3, "user_name": "you@example.com" }
}
```
`data` is the numeric **user_id**, needed as a parameter on several other endpoints. `user.token` is the session token used for signing (see 2.1).

### 2.3 `POST api/station/list` (confirmed)

Request:
```json
{
  "user_id": 100001,
  "station_name": "",
  "status": null,
  "station_type": null,
  "offset": 0,
  "rows": 10,
  "installer_name": "",
  "user_name": "",
  "export_type": 0
}
```

Response (`data`):
```json
{
  "total": 1,
  "list": [
    {
      "station_name": "Wallbox 000000",
      "enduser_name": "000000_Jan_Novak",
      "station_id": 200001,
      "photos": "https://cdn.example.com/station/placeholder.png",
      "station_capacity": 11.0,
      "installer_name": "InstallerCompany",
      "grid_time": "2025-05-03",
      "sum_energy": 1234.5,
      "day_energy": 0.0,
      "timezone_id": 29,
      "equ_count": 1,
      "station_type": 8,
      "order_id": 2,
      "status": 0
    }
  ]
}
```
`station_type == 8` identifies a wallbox / AC charging pile station (as opposed to inverters, storage, hybrid systems, etc. — see the `equipTypeArr`/`typeArr` enums in the JS for the full list of `station_type` values).

### 2.4 `POST api/charging/index` — realtime wallbox status (confirmed, this is the main "read everything" call)

Request:
```json
{ "inv_sn": "ABC0123456DEF789" }
```

Response (`data`), field-for-field as observed live (values below are a real idle-state capture, sanitized of identifying info):
```json
{
  "phase": 1,
  "charger_total_energy": 3244.1,
  "pv": {
    "inv_sn": "ABC0123456DEF789",
    "import_grid": 1,
    "min_solar_power": 8000,
    "boost": 0,
    "manual_energy": 0.0,
    "start_time": null,
    "stop_time": null,
    "auto_time": null,
    "auto_energy": 0.0,
    "last_operated_time": "2026-08-02 18:38:37"
  },
  "state2": 0,
  "mode": 1,
  "max_cur": 7.0,
  "max_power": 22000,
  "unit": 12,
  "charger_total_cost": 8585,
  "charger_cur": 0,
  "charger_per_energy": 0.0,
  "charger_per_cost": 0.0,
  "charger_power": 0,
  "unit_code": "Kč",
  "state": 2,
  "charger_vol": 236.5,
  "charger_per_time": 0.0
}
```

Field meanings (confirmed via the SPA's i18n string tables, cross-checked against the response above):

| Field | Meaning | Confirmed enum / unit |
|---|---|---|
| `charger_power` | Live charging power | W |
| `charger_vol` | Live voltage | V |
| `charger_cur` | Live current | A |
| `charger_total_energy` | Lifetime energy delivered | kWh |
| `charger_total_cost` | Lifetime cost, in `unit_code` currency | — |
| `charger_per_energy` / `charger_per_cost` / `charger_per_time` | Current/last session energy, cost, duration | kWh / currency / minutes (unit inferred) |
| `unit_code` | Currency symbol, e.g. `"Kč"` | string |
| `max_cur` / `max_power` | User-configured current/power limit | A / W |
| `phase` | `0` = single phase, `1` = three phase | confirmed via `phaseArr` i18n |
| `mode` | `0` = fast, `1` = PV/solar, `2` = off-peak | confirmed via `modeArr` i18n; `mode:1` in the sample above matches the populated `pv` object |
| `state2` | **This is the field the portal UI actually displays as "state"** — see enum below | confirmed via `pileState` i18n array |
| `state` | A second, less-used status code; the UI reads `state2`, not this one. Meaning not confirmed — expose as a diagnostic attribute only. | unconfirmed |
| `unit` | Unclear — possibly an internal price-unit id, not the same as `unit_code`. Expose as diagnostic. | unconfirmed |
| `pv.*` | Solar/PV-boost charging sub-settings: whether grid import is allowed, minimum solar power threshold before charging starts, manual boost flag/energy, scheduled start/stop | — |

`state2` enum (confirmed by matching array position against Chinese source strings `pile_state0`=空闲/idle, `pile_state124`=插枪未充电/plugged in not charging, `pile_state36`=充电中/charging, `pile_state5`=故障/fault):

| `state2` | Meaning |
|---|---|
| 0 | Idle |
| 1 | Plugged in, not charging |
| 2 | Plugged in, not charging |
| 3 | Charging |
| 4 | Plugged in, not charging |
| 5 | Fault |
| 6 | Charging |

### 2.5 `POST bg/equList` — device discovery (✅ confirmed against a live account)

Reconstructed from the SPA's `getPileIndex()` method, which calls a helper bound to export key `"n"` in the minified charging-api module. An earlier revision of this document guessed that helper was `api/charging/index` with a `{station_id, user_id, ...}` body — that guess was tested against a real RENAC EV-AC3P-11K account via a Docker-based Home Assistant instance and returned `{"code": 1, "data": null}` (no devices). Re-checking the minified JS's own export-to-function mapping (not just pattern-matching similar-looking code) showed export `"n"` is actually bound to a request against **`bg/equList`**, which was then confirmed live: the config flow correctly auto-discovers the wallbox with no manual serial entry needed.

Request:
```json
{ "user_id": 100001, "station_id": 200001, "status": 0, "offset": 0, "rows": 10 }
```
Response:
```json
{ "total": 1, "list": [ { "INV_SN": "ABC0123456DEF789", "...": "..." } ] }
```
Used to resolve a station's device serial (`INV_SN`) the first time, before switching to the confirmed single-device call in 2.4 for polling. If a station somehow returns zero devices (e.g. an unusual account setup), the config flow falls back to a free-text field so the serial can be entered manually.

### 2.6 `POST api/station/equipStat` (confirmed)

Request:
```json
{ "station_id": 200001, "user_id": 100001 }
```
Response (`data`):
```json
{ "total_online_equip": 1, "total_off_equip": 0, "total_alarm_equip": 0, "total_equip": 1 }
```

### 2.7 `POST api/charging/equ/charging_record` — session history (confirmed)

Request:
```json
{ "inv_sn": "ABC0123456DEF789", "begin_time": "2026-07-26T22:00:00.000Z", "end_time": "2026-08-03", "offset": 0, "rows": 5 }
```
Response (`data.results[]`), one entry per completed charging session:
```json
{
  "equ_sn": "ABC0123456DEF789",
  "begin_time": "2026-08-01 17:18:45",
  "begin_day": "2026-08-01",
  "status": "1",
  "end_time": "2026-08-01 17:26:03",
  "end_day": "2026-08-01",
  "per_energy": "0.7",
  "per_cost": "2.88",
  "day_energy": "0.7",
  "day_cost": "2.88",
  "mark": "0"
}
```

### 2.8 `POST api/charging/equ/detailChart` — time-series history (confirmed)

Request:
```json
{ "chart_type": 1, "inv_sn": "ABC0123456DEF789", "time": "2026-08-03" }
```
Response (`data.results[]`), one entry roughly per minute:
```json
{
  "upload_time": "2026-08-03 00:00:32",
  "CHARGER_VOL_A": 237.1, "CHARGER_VOL_B": 236.0, "CHARGER_VOL_C": 235.6,
  "CHARGER_CUR_A": 0.0, "CHARGER_CUR_B": 0.0, "CHARGER_CUR_C": 0.0,
  "CHARGER_TEMP": 31.0,
  "CHARGER_POWER": 0
}
```
Per-phase voltage/current is **only** available through this endpoint, not through `api/charging/index` — useful for a future "phase imbalance" or diagnostics sensor, not currently wired into the integration.

### 2.9 Other endpoints seen but not used by this integration

Extracted from the JS route table, listed for completeness / future extension: `api/station/weather`, `api/charging/fast`, `api/charging/pv`, `api/charging/off-peak`, `api/charging/equ/detail` (confirmed via decompiled code to return additional device metadata: `model`, `rated_power`, `reg_time`, `version`, per-phase `charger_vol_a/b/c`, `charger_cur_a/b/c` — not yet wired into the integration), `api/charging/equ/detailChart/export`, `api/user/info`, `api/user/changePwd`, `api/com/getWebVer`.

### 2.10 `api/charging/basic|fast|pv|off-peak` (read) and `api/charging/set` (write) — full wallbox settings ⚠️ derived from decompiled JS, not live-captured

Unlike every other endpoint in this document, this whole section was **not** confirmed by watching a real network request — the settings UI isn't reachable in the web portal without navigating to a specific device-settings view that a fresh account/session doesn't land on by default, and no HAR of it exists yet. Instead, the exact request-building code was located and read directly, in full: the settings form component (Vue component name `SetPile`, in `chunk-184c83ca` module `fb3b`, decompiled) has one `data.field` per input, and every Save button's `setMode(t)` handler diffs its tab's fields against the last-read snapshot and submits exactly what changed via `POST api/charging/set`. This is stronger evidence than a guessed URL+params shape (it's the literal code that builds the request), but it has not been exercised against the real API for anything beyond `max_output_cur` — **test carefully, on a wallbox where an unexpected setting isn't a safety problem, before relying on any of it.** Everything below **has** been verified end-to-end against the Docker mock server (`docker-compose.test.yml`) — a `number`/`select`/`switch`/`time` write reliably produces the exact payload documented here and is reflected back on the next read.

#### Reads

Four sibling endpoints, each `{"inv_sn": "<serial>"}` in, confirmed field names out (`readBasic()`/`readFast()`/`readPv()`/`readOffPeak()`):

| Endpoint | `data` fields |
|---|---|
| `POST api/charging/basic` | `charing_mode` (int; SPA's own spelling, missing a "g" — reproduce verbatim), `rfid`, `max_output_cur` (A), `protect_temp` (°C), `max_input_power`, `allow_charging_time_begin`/`_end` ("HH:mm"), `external_cur_sampling`, `meter_address`, `rate_number`, and `rate{N}_time_begin`/`_end`/`_rate` for `N` in `1..rate_number` (time-of-use tariff schedule) |
| `POST api/charging/fast` | `mode` (0=preset time/1=preset energy/2=preset cost), `time_number` (minutes), `time_begintime`, `time_day`, `energy_number` (kWh), `energy_begintime`, `energy_day`, `cost_number`, `cost_begintime`, `cost_day` |
| `POST api/charging/pv` | `import_grid` (0/1), `min_solar_power` (0–22000 W), `boost` (0=off/1=manual/2=intelligent), `manual_energy` (kWh), `start_time`, `stop_time`, `auto_time`, `auto_energy` (kWh) |
| `POST api/charging/off-peak` | `boost` (0/1), `peak_time` (comma-joined 0/1 flags, one per configured tariff-rate slot from `api/charging/basic`), `auto_time`, `auto_energy` (kWh), `balance` (0/1, load balancing), `balance_power` (W) |

`*_begintime` fields use the sentinel `"255:255"` for "no scheduled start / charge immediately on plug-in" rather than a real time — the web form's "plug and charge" toggle sets this. The sample values in each fixture (`tests/fixtures/renac_api/charging_{basic,fast,pv,off_peak}.json`) are **not from a live capture** — they were constructed from the field names and plausible defaults, not sanitized real data like everywhere else in this document.

#### Write — `POST api/charging/set`

```json
{ "equ_sn": "ABC0123456DEF789", "type": 2, "ids": "max_output_cur", "params": "16" }
```
Response: the standard `{"code": 1, ...}` envelope with no meaningful `data`. `ids`/`params` are parallel comma-joined lists — multiple fields can be changed in one call. Numbers must be formatted the way JS's own number-to-string conversion would (`16`, not `16.0`) — `RenacApiClient.async_set_charging` handles this.

Every `type` value observed in `setMode()`, what it writes to, and its confirmation status:

| `type` | Group | Fields | HA entity confidence |
|---|---|---|---|
| 1 | RFID | `rfid` | Not implemented as an entity (security-sensitive, low value) |
| 2 | Basic | `charing_mode`, `max_output_cur`, `protect_temp`, `max_input_power`, `allow_charging_time_begin`/`_end`, `external_cur_sampling`, `meter_address`, `rate{N}_*` | `max_output_cur` implemented (`number.*_max_current_limit`); `charing_mode`→`select.*_charge_authorization`, `protect_temp`→`number.*_protect_temperature`, `meter_address`→`number.*_meter_address`, `external_cur_sampling`→`select.*_external_current_sampling`, `allow_charging_time_begin`/`_end`→`time.*` all implemented. `max_input_power` and the `rate{N}_*` tariff schedule are **not** implemented (the latter needs a list-of-slots UI HA doesn't have a clean built-in entity for) |
| 3 | Overall mode | `charger_mode` (0=fast/1=pv/2=off_peak) | Implemented: `select.*_charge_mode` (reads the realtime `api/charging/index` `mode` field, writes type=3) |
| 4 | Fast-charge schedule | `mode` (0/1/2) + the matching `time_*`/`energy_*`/`cost_*` trio | `mode`→`select.*_fast_charge_plan`, `energy_number`→`number.*_fast_charge_energy_target`, `cost_number`→`number.*_fast_charge_cost_target`, all three `*_begintime`→`time.*` implemented. `time_number` (a duration, not a clock time) is **not** implemented |
| 5 | PV/solar-boost | `import_grid`, `min_solar_power`, `boost` (0/1/2), + `manual_energy`/`start_time`/`stop_time` (boost=1) or `auto_time`/`auto_energy` (boost=2) | All fields implemented across `switch.*_pv_allow_grid_import`, `number.*_pv_min_solar_power`, `select.*_pv_boost_mode`, `number.*_pv_manual_boost_energy_target`, `number.*_pv_intelligent_boost_energy_target`, and four `time.*` entities |
| 6 | Off-peak schedule **and** load balancing (shared `type`, distinguished only by `ids`) | Off-peak: `boost`, `peak_time`, `auto_time`, `auto_energy`. Balance: `balance`, `balance_power` | `boost`→`switch.*_off_peak_boost`, `auto_time`→`time.*_off_peak_boost_end`, `auto_energy`→`number.*_off_peak_boost_energy_target`, `balance`→`switch.*_load_balance`, `balance_power`→`number.*_load_balance_power` implemented. `peak_time` (per-slot tariff selection, needs the `rate{N}_*` schedule from type 2) is **not** implemented |

**A note on partial writes:** the SPA always submits a full tab's worth of fields together (e.g. changing PV mode resends `import_grid`+`min_solar_power`+`boost` even if only one changed). This integration instead sends exactly one field per entity write, on the assumption — confirmed only for `type 1`/`rfid`, which the SPA itself always sends alone — that the API accepts partial field sets per `type`. This was **not** an issue against the Docker mock (which just applies whatever `ids` it's given), but a real account might behave differently; if a lone-field write for type 4/5/6 doesn't take effect, try `RenacApiClient.async_set_charging()` with all of that tab's fields included together.

**Home Assistant integration:** see the file table in §3 — `number.py`, `select.py`, `switch.py`, and `time.py` between them implement 24 read/write entities across all six `type` values, backed by a new `RenacSettingsCoordinator` (`coordinator.py`) that polls `api/charging/basic|fast|pv|off-peak` every 5 minutes (`SETTINGS_SCAN_INTERVAL` in `const.py`) — much slower than the realtime 30s poll, since these change rarely and are unconfirmed-write endpoints. A failure fetching any one settings group is logged and that group's entities simply go `unavailable`, rather than blocking setup of the confirmed read-only sensors. `max_current_limit`, `select.*_charge_mode`, and `switch.*_charging` (2.11) are the exceptions: they read from the realtime coordinator instead (faster feedback after a write, and none of `mode`/`charger_cmd` are part of any `charging/basic|fast|pv|off-peak` response anyway). **None of this (except §2.11) has been tested against a real account** — do that (starting with something low-risk like `meter_address` or a `select` before anything current/power-related) before treating it as fully confirmed, and update this section and §1's status table once you have.

### 2.11 `POST api/charging/set` type=3, `charger_cmd` — start/stop charging ✅ confirmed live

Unlike everything in §2.10, this one **was** captured from a real network request: a HAR export of the web portal's "turn on"/"turn off charging" buttons being clicked (2026-08-03). It is the only *write* action in this entire integration verified against a live account rather than derived from decompiled JS.

Request (start):
```json
{ "equ_sn": "ABC0123456DEF789", "type": 3, "ids": "charger_cmd", "params": 1 }
```
Request (stop): identical with `"params": 2`. Response both times: `{"code": 1, "msg": "0000", "data": null}`.

Two things make this call distinctive:
- **`type: 3` is shared** between this and the overall mode switch (`ids: "charger_mode"`, §2.10) — confirms `type` really is just a "which device command" selector, not a 1:1 mapping to a single field, consistent with `type: 6` also being shared between off-peak schedule and load balancing.
- **`params` is a raw JSON integer** (`1`, not `"1"`) — every other confirmed `charging/set` write in this document sends `params` as a comma-joined *string*, built by the settings form's generic diff-and-join code. The start/stop buttons evidently call the API directly with a literal argument instead of going through that shared code path. `RenacApiClient.async_set_charger_command()` sends the literal integer to match; every other write method still sends strings via `async_set_charging()`.

No follow-up `api/charging/index` request was captured in the same HAR, so the resulting `state2` transition wasn't directly observed — but both calls returned `code: 1`. **Home Assistant integration:** `switch.*_charging` (`switch.py`) — `is_on` reflects the wallbox's actual reported `state2` (charging vs. not, `CHARGE_STATES`/`CHARGING_ACTIVE_STATES` in `const.py`), not just the last command sent, so it correctly shows off if you send "start" with no vehicle plugged in. Verified end-to-end against the Docker mock server (full round trip, including the `params` int-vs-string distinction).

---

## 3. Code architecture

Code lives in [`custom_components/renac_wallbox/`](../custom_components/renac_wallbox/):

| File | Responsibility |
|---|---|
| [`api.py`](../custom_components/renac_wallbox/api.py) | `RenacApiClient` — login, request signing, all confirmed endpoint calls |
| [`const.py`](../custom_components/renac_wallbox/const.py) | Domain, base URL, signing salt, response codes, confirmed enums |
| [`coordinator.py`](../custom_components/renac_wallbox/coordinator.py) | `RenacWallboxCoordinator` polls `api/charging/index` (2.4) every 30s (configurable); `RenacSettingsCoordinator` polls `api/charging/basic|fast|pv|off-peak` (2.10) every 5 minutes, best-effort (a failed group doesn't block setup) |
| [`config_flow.py`](../custom_components/renac_wallbox/config_flow.py) | UI setup: base URL + email + password → pick station → pick device |
| [`sensor.py`](../custom_components/renac_wallbox/sensor.py) | One entity per confirmed realtime field (power, voltage, current, energy, cost, state, phase, max power limit) |
| [`binary_sensor.py`](../custom_components/renac_wallbox/binary_sensor.py) | `fault` binary sensor (`state2 == 5`) |
| [`number.py`](../custom_components/renac_wallbox/number.py) | 9 numeric read/write entities: max current limit (realtime-backed), protect temp, meter address, PV min. solar power, PV/off-peak/fast energy targets, fast cost target (all settings-backed, 2.10) |
| [`select.py`](../custom_components/renac_wallbox/select.py) | 5 enum read/write entities: overall charge mode (realtime-backed), charge authorization, external current sampling, PV boost mode, fast charge plan (all settings-backed, 2.10) |
| [`switch.py`](../custom_components/renac_wallbox/switch.py) | ✅ `charging` — start/stop charging (realtime-backed, **confirmed live**, 2.11), plus 3 settings-backed boolean entities: PV grid import, off-peak boost, load balance enable (2.10) |
| [`time.py`](../custom_components/renac_wallbox/time.py) | 9 HH:mm read/write entities: allowed charging window, fast/PV/off-peak schedule times (2.10) |
| [`manifest.json`](../custom_components/renac_wallbox/manifest.json), [`strings.json`](../custom_components/renac_wallbox/strings.json), [`translations/`](../custom_components/renac_wallbox/translations/) | HA metadata + EN/CZ config-flow and entity translations |

One config entry = one wallbox device (`inv_sn`). Multi-wallbox accounts add the integration once per device (the config flow walks you through picking the station and device if there is more than one).

Not yet implemented, left as future work: session-history sensor from 2.7, per-phase diagnostics from 2.8, and any write/control entities against `api/charging/set` (2.9) since its request payload has not been confirmed against a live account.

---

## 4. Known gaps / what an implementing agent should verify next

1. **Regions other than Europe** — confirm the base URL pattern for Asia/South America (or any other region) against a real account before shipping to non-EU users; currently only a guessed hostname pattern is offered.
2. **`api/charging/set` / `api/charging/basic` (§2.10)** — implemented and Docker-mock-tested, but the request shape was derived from decompiled JS, not a live capture. Confirm against a real account (ideally via a fresh HAR of the settings-form Save action) before trusting the write path in production, especially on hardware where an unexpected current spike matters.
3. **`max_output_cur` min/max range** — `number.py`'s `MIN_CURRENT_A`/`MAX_CURRENT_A` (6/32 A) are a guess; the web form itself declares no bounds. Replace with your wallbox's real supported range once known (check the physical unit's rating plate or installer documentation).
4. **Other `api/charging/set` types** (1=RFID, 3=mode switch) and other `basic` fields (`protect_temp`, `allow_charging_time_*`, time-of-use tariff schedule) — field names are known (§2.10) but not wired into any HA entity; natural next additions once the write path above is live-confirmed.
5. **Token lifetime / re-login cadence** — the integration re-logs in reactively (on `msg == "1000"`), but the actual TTL of a token was not measured; consider whether a proactive re-login on a timer is worth adding once observed in practice.
6. **`state` vs `unit` fields** — currently unexplained; if you find their meaning (e.g. by triggering a fault or changing currency), fold it into `const.py`.

## 4.1 Security notes

* The RENAC login endpoint accepts a **plaintext password over HTTPS** — there is no client-side hashing to preserve. Store credentials the same way Home Assistant stores any other integration's credentials (in the config entry, encrypted at rest by HA's storage if configured).
* The signing salt (`SIGN_SALT` in `const.py`) is a static string baked into RENAC's own public web client — treating it as a secret would be pointless (it ships in every page load), but do not present it as *your* code's secret if this project is published.
* This integration only performs **read** operations against documented, observed endpoints. It never writes to `api/charging/set` or similar control endpoints as shipped.

---

## 5. Testing (no real credentials required)

Two independent test layers exist, both driven entirely by **sanitized, real-shaped fixtures** derived from the original HAR capture (`tests/fixtures/renac_api/*.json` — same placeholder values as §2's examples). Neither layer ever contacts the real RENAC cloud or needs a real email/password/token.

**1. Unit tests** (`tests/test_api.py`) — spin up a throwaway in-process `aiohttp` server that replays the fixtures and independently re-implements the `Token`/`timestamp`/`sign` check, so the tests fail if `api.py`'s signing logic ever drifts from the real scheme:
```bash
pip install -r tests/requirements-test.txt
pytest tests/test_api.py -v
```

**2. Full HACS-integration end-to-end test, in Docker** (`docker-compose.test.yml`) — runs an actual Home Assistant core container with `custom_components/renac_wallbox` mounted in exactly as HACS would install it, alongside a small mock RENAC API container (`tests/mock_server/`) serving the same fixtures over HTTP and enforcing the real signing scheme. This exercises the *real* config flow, coordinator, and entity platforms inside a real HA instance — it caught two real bugs during development (an invalid `state_class`/`device_class` combination on the session-energy sensor, and a plain string passed where HA expects an `EntityCategory` enum on the three diagnostic sensors — both now fixed in `sensor.py`).

```bash
docker compose -f docker-compose.test.yml up --build -d
# wait ~10s for Home Assistant to start, then complete onboarding + the
# config flow against the mock server (http://mock-renac-api:8084) using
# HA's own REST API, or drive it through the UI at
# http://localhost:18123 with any email/password (the mock accepts
# anything) and base URL http://mock-renac-api:8084.
docker compose -f docker-compose.test.yml down
```
Expect to see `sensor.wallbox_..._power`, `..._voltage`, `..._state` (`idle`), `..._charge_mode` (`pv`), etc. appear under `/api/states`, matching the field values documented in §2.4.

---
---

# 🇨🇿 RENAC Wallbox — API referenční dokumentace a technické poznámky

Kompletní reverzně odvozená dokumentace cloudového API RENAC použitého v [`custom_components/renac_wallbox/`](../custom_components/renac_wallbox/). Pokud chcete integraci jen nainstalovat a používat, přejděte místo toho na hlavní [README](../README.md) — tento dokument je pro každého, kdo kód rozšiřuje, ověřuje nějaké tvrzení, nebo navazuje na rozdělanou práci (AI agent i člověk).

> 🇨🇿 Česká verze níže. / 🇬🇧 English version first, Czech version below.

---

## 1. Stav

> ✅ **Úspěšně otestováno end-to-end na reálném wallboxu RENAC EV-AC3P-11K** — přihlášení, automatické vyhledání stanice/zařízení i živé čtení senzorů (výkon, napětí, proud, energie, náklady, stav, režim) potvrzeno funkční přes celý instalační postup HACS uvnitř běžícího Home Assistant.

| Část | Stav |
|---|---|
| Autentizace (přihlášení, podepisování tokenu) | ✅ Ověřeno na reálném účtu |
| `api/station/list` | ✅ Ověřeno (reálný zachycený provoz) |
| `api/charging/index` (jedno zařízení, `{inv_sn}`) | ✅ Ověřeno (reálný zachycený provoz) — **toto je volání pro "vyčtení všech dat wallboxu"** |
| `bg/equList` (vyhledání zařízení podle stanice) | ✅ Ověřeno na reálném účtu (dřívější odhad `api/charging/index` s jinými parametry byl otestován naživo a ukázal se jako chybný — viz §2.5) |
| `api/station/equipStat` | ✅ Ověřeno (reálný zachycený provoz) |
| `api/charging/equ/charging_record` (historie nabíjecích relací) | ✅ Ověřeno (reálný zachycený provoz) |
| `api/charging/equ/detailChart` (časová řada historie) | ✅ Ověřeno (reálný zachycený provoz) |
| `api/charging/basic\|fast\|pv\|off-peak` (čtení nastavení) | ⚠️ Odvozeno z dekompilovaného JS (skutečný kód sestavující požadavek, ne odhad tvaru), nezachyceno naživo — viz §2.10 |
| `api/charging/set` typ=3, `charger_cmd` (start/stop nabíjení) | ✅ Ověřeno naživo — zachyceno z reálného kliknutí na "zapnout"/"vypnout nabíjení" ve webovém portálu, jediná zápisová akce v projektu ověřená proti reálnému síťovému požadavku. `switch.*_charging` — viz §2.11 |
| `api/charging/set` všech 6 hodnot `type` (zápis nastavení vč. max. proudu) | ⚠️ 24 entit implementováno napříč `number`/`select`/`switch`/`time`, odvozeno z dekompilovaného JS, otestováno proti Docker mock serveru (kompletní cyklus čtení/zápis, bez chyb), zatím ne na reálném účtu — viz §2.10 |
| Integrace Home Assistant (`custom_components/renac_wallbox/`) | ✅ Čtecí část otestována end-to-end na reálném wallboxu RENAC EV-AC3P-11K přes celý instalační postup HACS; zápisová část nastavení (24 entit) zatím jen v Docker mocku; zápis start/stop `charger_cmd` je ověřen naživo (viz §5) |
| Jiné regiony než Evropa | ⚠️ Vzor základní URL je pouze odhadnut, neověřeno |

**Jak bylo API zjištěno:** webový portál RENAC je Vue.js SPA. Jeho produkční JS balíčky (`app.*.js` a chunk soubory) byly staženy a prohledány přímo (bez nutnosti přihlášení, jde o veřejný klientský kód) na řetězce API cest, axios request/response interceptory a logiku přihlašovacího formuláře. Tím se získalo autentizační schéma a většina cest/parametrů endpointů. Následně byl použit **HAR záznam reálné přihlášené relace prohlížeče proti skutečnému wallboxu** k ověření přesných tvarů JSON požadavků/odpovědí u endpointů označených ✅ výše. **Všechny identifikační hodnoty z tohoto záznamu (token, ID uživatele, sériové číslo zařízení, ID stanice, název stanice, jméno majitele, jméno instalatéra) byly před zápisem do tohoto repozitáře nahrazeny fiktivními hodnotami** — reálné jsou pouze *názvy* polí a realistické *tvary/typy* dat. Samotný token nebyl nikdy zapsán mimo původní lokální HAR soubor a v tomto repozitáři ani jeho historii se nikde nenachází.

**Předchozí práce / křížová kontrola oproti:**
- Oficiální **"RENAC SEC API Documentation" v2.0.7** (partnerské/open-platform PDF šířené na [fóru ioBroker](https://forum.iobroker.net/)) nezávisle dokumentuje `api/user/login` a `api/station/list` se zcela stejnými názvy parametrů a polí odpovědi, jaké byly nalezeny zde — to potvrzuje tyto dva endpointy nezávisle na samotném reverzním inženýrství z JS. Tento dokument cílí na jiný výchozí hostitel (`153.le-pv.com:8082`, bez HTTPS, bez podepisovacích hlaviček) a **vůbec nezmiňuje žádný endpoint pro wallbox/nabíjení EV, ani schéma hlaviček `Token`/`timestamp`/`sign`** používané produkčním webovým portálem — endpointy pro nabíjecí stanice a schéma podepisování požadavků popsané v §2 níže jsou původní zjištění tohoto projektu, nikoli převzatá z onoho dokumentu.
- [`raschy/ioBroker.renacidc`](https://github.com/raschy/ioBroker.renacidc), nezávislý ioBroker adaptér pro **solární střídače** RENAC (ne wallboxy), uvádí v changelogu záznam o "speciálním API podpisu", který si musel sám reverzně odvodit — což potvrzuje, že cloud RENAC skutečně vyžaduje vlastní podepisování požadavků nad rámec toho, co dokumentuje oficiální PDF, aniž by byl zdrojový kód onoho projektu zde konzultován či kopírován.
- [`gastush/ha-renac`](https://github.com/gastush/ha-renac) a [`HA1Andrzej/RENAC-MODBUS`](https://github.com/HA1Andrzej/RENAC-MODBUS) jsou existující integrace Home Assistant pro **hybridní/on-grid solární střídače** RENAC přes lokální Modbus/RS485 — zcela odlišný přenosový kanál (LAN, ne cloud) a produktová řada oproti AC wallboxu popsanému zde. Žádný překryv v kódu ani endpointech.

---

## 2. Ověřený kontrakt API

Základní URL (region Evropa, ověřeno): `https://europe.renacpower.com:8084/`
Webová aplikace ji za běhu čte z globální proměnné `window.baseUrl.path`, nastavené mimo JS balíček. Ostatní regiony (v UI se objevily možnosti Asie a Jižní Amerika) pravděpodobně používají vzor `https://<region>.renacpower.com:8084/`, ale **to nebylo ověřeno**. Základní URL považujte za konfigurovatelnou, ne pevně danou.

Poznámka: oficiální partnerské PDF API (viz poznámka o předchozí práci výše) dokumentuje *jiného* výchozího hostitele, `http://153.le-pv.com:8082` (obyčejné HTTP, bez podepisovacích hlaviček), pro stejné endpointy `api/user/login` / `api/station/list`. Jde pravděpodobně o starší nebo globální záložní nasazení; endpointy pro wallbox/nabíjení EV a požadavek na podepisování hlavičkami `Token`/`timestamp`/`sign` byly pozorovány pouze na regionálním hostiteli `europe.renacpower.com:8084`, který používá současný webový portál — proto je to výchozí cíl této integrace.

### 2.1 Autentizace a podepisování požadavků (ověřeno)

Každý požadavek (kromě `login`, `register`, `getWebVer`, `sendEmailCode`, `forgetpwd`, `alertRenac`) musí nést tři hlavičky odvozené z tokenu relace:

```
Token: <token z přihlášení>
timestamp: <aktuální unixový čas v sekundách, jako řetězec>
sign: MD5(token + str(timestamp) + "9P@3kF7sD2&zX5cV8bNm1qR4tY6uI0o")
```

Výše uvedený "salt" řetězec je pevně zakódovaný v klientském JS (není to tajemství vázané na uživatele) — byl extrahován doslovně z request interceptoru. `sign` je malými písmeny hex MD5. `Content-Type` pro POST těla je `application/json;charset=utf-8`. Všechna volání jsou `POST`, i logicky "čtecí".

Obálka odpovědi pro každý endpoint:

```json
{ "code": 1, "msg": "0000", "data": { /* obsah, tvar se liší podle endpointu */ } }
```

* `code == 1` → úspěch, použij `data`.
* `code == 400` a `msg == "1000"` → token je neplatný/expirovaný → **znovu se přihlásit** (`api/user/login`) a jednou zopakovat požadavek.
* `code == 400` a `msg == "1008"` → hodiny klienta jsou posunuté; `data` obsahuje odchylku v minutách. Protože `sign` je časově závislý, udržujte čas hostitele synchronizovaný (NTP), jinak API odmítne každý podepsaný požadavek.

### 2.2 `POST api/user/login` (ověřeno)

Požadavek:
```json
{ "login_name": "vas@email.cz", "pwd": "vase-heslo" }
```
Heslo se posílá **v čistém textu** — SPA jej na klientovi nehashuje ani nešifruje. Jedinou ochranou je TLS. V JS je vidět demo účet (`888@qq.com` / `123456`) používaný tlačítkem "vyzkoušet demo" na portálu.

Odpověď:
```json
{
  "code": 1,
  "msg": "0000",
  "data": 100001,
  "user": { "token": "...", "role_id": 3, "user_name": "vas@email.cz" }
}
```
`data` je číselné **user_id**, potřebné jako parametr u dalších endpointů. `user.token` je token relace použitý pro podepisování (viz 2.1).

### 2.3 `POST api/station/list` (ověřeno)

Požadavek:
```json
{
  "user_id": 100001,
  "station_name": "",
  "status": null,
  "station_type": null,
  "offset": 0,
  "rows": 10,
  "installer_name": "",
  "user_name": "",
  "export_type": 0
}
```

Odpověď (`data`):
```json
{
  "total": 1,
  "list": [
    {
      "station_name": "Wallbox 000000",
      "enduser_name": "000000_Jan_Novak",
      "station_id": 200001,
      "photos": "https://cdn.example.com/station/placeholder.png",
      "station_capacity": 11.0,
      "installer_name": "InstallerCompany",
      "grid_time": "2025-05-03",
      "sum_energy": 1234.5,
      "day_energy": 0.0,
      "timezone_id": 29,
      "equ_count": 1,
      "station_type": 8,
      "order_id": 2,
      "status": 0
    }
  ]
}
```
`station_type == 8` identifikuje stanici typu wallbox / AC nabíjecí bod (na rozdíl od střídačů, baterií, hybridních systémů atd. — kompletní seznam hodnot `station_type` je v JS v enumech `equipTypeArr`/`typeArr`).

### 2.4 `POST api/charging/index` — stav wallboxu v reálném čase (ověřeno, hlavní volání pro "vyčtení všeho")

Požadavek:
```json
{ "inv_sn": "ABC0123456DEF789" }
```

Odpověď (`data`), pole po poli přesně jak bylo zachyceno naživo (hodnoty níže jsou reálný záznam nečinného stavu, očištěný o identifikační údaje):
```json
{
  "phase": 1,
  "charger_total_energy": 3244.1,
  "pv": {
    "inv_sn": "ABC0123456DEF789",
    "import_grid": 1,
    "min_solar_power": 8000,
    "boost": 0,
    "manual_energy": 0.0,
    "start_time": null,
    "stop_time": null,
    "auto_time": null,
    "auto_energy": 0.0,
    "last_operated_time": "2026-08-02 18:38:37"
  },
  "state2": 0,
  "mode": 1,
  "max_cur": 7.0,
  "max_power": 22000,
  "unit": 12,
  "charger_total_cost": 8585,
  "charger_cur": 0,
  "charger_per_energy": 0.0,
  "charger_per_cost": 0.0,
  "charger_power": 0,
  "unit_code": "Kč",
  "state": 2,
  "charger_vol": 236.5,
  "charger_per_time": 0.0
}
```

Význam polí (ověřeno pomocí i18n textových tabulek SPA, zkříženo s odpovědí výše):

| Pole | Význam | Ověřená jednotka / výčet |
|---|---|---|
| `charger_power` | Aktuální nabíjecí výkon | W |
| `charger_vol` | Aktuální napětí | V |
| `charger_cur` | Aktuální proud | A |
| `charger_total_energy` | Celková dodaná energie za dobu životnosti | kWh |
| `charger_total_cost` | Celkové náklady za dobu životnosti, v měně `unit_code` | — |
| `charger_per_energy` / `charger_per_cost` / `charger_per_time` | Energie/náklady/doba trvání aktuální (poslední) relace | kWh / měna / minuty (jednotka odvozena) |
| `unit_code` | Symbol měny, např. `"Kč"` | řetězec |
| `max_cur` / `max_power` | Uživatelem nastavený limit proudu/výkonu | A / W |
| `phase` | `0` = jedna fáze, `1` = tři fáze | ověřeno přes i18n `phaseArr` |
| `mode` | `0` = rychlé, `1` = PV/solární, `2` = nízký tarif | ověřeno přes i18n `modeArr`; `mode:1` ve vzorku výše odpovídá vyplněnému objektu `pv` |
| `state2` | **Toto je pole, které UI portálu skutečně zobrazuje jako "stav"** — výčet níže | ověřeno přes i18n pole `pileState` |
| `state` | Druhý, méně používaný stavový kód; UI čte `state2`, ne toto pole. Význam neověřen — vystavit pouze jako diagnostický atribut. | neověřeno |
| `unit` | Nejasné — možná interní ID cenové jednotky, není totéž co `unit_code`. Vystavit jako diagnostický atribut. | neověřeno |
| `pv.*` | Podnastavení solárního/PV-boost nabíjení: zda je povolen odběr ze sítě, minimální práh solárního výkonu pro spuštění nabíjení, příznak/energie ručního boostu, plánovaný start/stop | — |

Výčet `state2` (ověřeno srovnáním pozice v poli s čínskými zdrojovými řetězci `pile_state0`=空闲/nečinný, `pile_state124`=插枪未充电/připojeno, nenabíjí se, `pile_state36`=充电中/nabíjí se, `pile_state5`=故障/porucha):

| `state2` | Význam |
|---|---|
| 0 | Nečinný |
| 1 | Připojeno, nenabíjí se |
| 2 | Připojeno, nenabíjí se |
| 3 | Nabíjí se |
| 4 | Připojeno, nenabíjí se |
| 5 | Porucha |
| 6 | Nabíjí se |

### 2.5 `POST bg/equList` — vyhledání zařízení (✅ ověřeno na reálném účtu)

Rekonstruováno z metody `getPileIndex()` v SPA, která volá pomocnou funkci navázanou na exportní klíč `"n"` v minifikovaném modulu charging-api. Dřívější verze tohoto dokumentu odhadovala, že jde o `api/charging/index` s tělem `{station_id, user_id, ...}` — tento odhad byl otestován na reálném účtu RENAC EV-AC3P-11K přes Docker instanci Home Assistant a vrátil `{"code": 1, "data": null}` (žádná zařízení). Opětovná kontrola skutečného mapování exportů na funkce v minifikovaném JS (ne jen podobnost vzoru kódu) ukázala, že export `"n"` je ve skutečnosti navázán na požadavek proti **`bg/equList`**, což bylo následně ověřeno naživo: config flow nyní správně automaticky najde wallbox bez nutnosti ručního zadání sériového čísla.

Požadavek:
```json
{ "user_id": 100001, "station_id": 200001, "status": 0, "offset": 0, "rows": 10 }
```
Odpověď:
```json
{ "total": 1, "list": [ { "INV_SN": "ABC0123456DEF789", "...": "..." } ] }
```
Používá se k prvotnímu zjištění sériového čísla zařízení (`INV_SN`) dané stanice, než se přejde na ověřené volání pro jedno zařízení z bodu 2.4 pro pravidelné dotazování. Pokud by nějaká stanice vrátila nula zařízení (např. neobvyklé nastavení účtu), config flow nabídne textové pole pro ruční zadání sériového čísla.

### 2.6 `POST api/station/equipStat` (ověřeno)

Požadavek:
```json
{ "station_id": 200001, "user_id": 100001 }
```
Odpověď (`data`):
```json
{ "total_online_equip": 1, "total_off_equip": 0, "total_alarm_equip": 0, "total_equip": 1 }
```

### 2.7 `POST api/charging/equ/charging_record` — historie relací (ověřeno)

Požadavek:
```json
{ "inv_sn": "ABC0123456DEF789", "begin_time": "2026-07-26T22:00:00.000Z", "end_time": "2026-08-03", "offset": 0, "rows": 5 }
```
Odpověď (`data.results[]`), jeden záznam na dokončenou nabíjecí relaci:
```json
{
  "equ_sn": "ABC0123456DEF789",
  "begin_time": "2026-08-01 17:18:45",
  "begin_day": "2026-08-01",
  "status": "1",
  "end_time": "2026-08-01 17:26:03",
  "end_day": "2026-08-01",
  "per_energy": "0.7",
  "per_cost": "2.88",
  "day_energy": "0.7",
  "day_cost": "2.88",
  "mark": "0"
}
```

### 2.8 `POST api/charging/equ/detailChart` — časová řada historie (ověřeno)

Požadavek:
```json
{ "chart_type": 1, "inv_sn": "ABC0123456DEF789", "time": "2026-08-03" }
```
Odpověď (`data.results[]`), přibližně jeden záznam za minutu:
```json
{
  "upload_time": "2026-08-03 00:00:32",
  "CHARGER_VOL_A": 237.1, "CHARGER_VOL_B": 236.0, "CHARGER_VOL_C": 235.6,
  "CHARGER_CUR_A": 0.0, "CHARGER_CUR_B": 0.0, "CHARGER_CUR_C": 0.0,
  "CHARGER_TEMP": 31.0,
  "CHARGER_POWER": 0
}
```
Napětí/proud po jednotlivých fázích je dostupné **pouze** přes tento endpoint, ne přes `api/charging/index` — užitečné pro budoucí senzor "nevyváženosti fází" nebo diagnostiku, zatím do integrace nezapojeno.

### 2.9 Další nalezené, ale nepoužité endpointy

Extrahováno z tabulky rout v JS, uvedeno pro úplnost / budoucí rozšíření: `api/station/weather`, `api/charging/fast`, `api/charging/pv`, `api/charging/off-peak`, `api/charging/equ/detail` (ověřeno dekompilací kódu, že vrací další metadata zařízení: `model`, `rated_power`, `reg_time`, `version`, po fázích `charger_vol_a/b/c`, `charger_cur_a/b/c` — zatím nezapojeno do integrace), `api/charging/equ/detailChart/export`, `api/user/info`, `api/user/changePwd`, `api/com/getWebVer`.

### 2.10 `api/charging/basic|fast|pv|off-peak` (čtení) a `api/charging/set` (zápis) — kompletní nastavení wallboxu ⚠️ odvozeno z dekompilovaného JS, nezachyceno naživo

Na rozdíl od každého jiného endpointu v tomto dokumentu celá tato sekce **nebyla** potvrzena sledováním reálného síťového požadavku — nastavovací UI není ve webovém portálu dosažitelné bez navigace do konkrétní obrazovky nastavení zařízení, na kterou čerstvý účet/relace defaultně nedojde, a HAR záznam takové akce zatím neexistuje. Místo toho byl přímo a kompletně dohledán a přečten skutečný kód sestavující požadavky: komponenta formuláře nastavení (Vue komponenta `SetPile`, v `chunk-184c83ca` modulu `fb3b`, dekompilováno) má jedno `data.pole` na každý vstup, a handler `setMode(t)` každého tlačítka Uložit porovná pole své záložky s posledně načteným stavem a odešle přesně to, co se změnilo, přes `POST api/charging/set`. To je silnější důkaz než odhadnutý tvar URL+parametrů (jde o doslovný kód, který požadavek sestavuje), ale nebylo to vyzkoušeno proti reálnému API kromě `max_output_cur` — **než se na cokoli z toho spolehnete, otestujte to opatrně, na wallboxu, kde neočekávané nastavení není bezpečnostní problém.** Vše níže **bylo** ověřeno end-to-end proti Docker mock serveru (`docker-compose.test.yml`) — zápis přes `number`/`select`/`switch`/`time` spolehlivě vyprodukuje přesně zdokumentovaný payload a odrazí se zpět při dalším čtení.

#### Čtení

Čtyři sesterské endpointy, každý `{"inv_sn": "<sériové číslo>"}` na vstupu, ověřené názvy polí na výstupu (`readBasic()`/`readFast()`/`readPv()`/`readOffPeak()`):

| Endpoint | Pole `data` |
|---|---|
| `POST api/charging/basic` | `charing_mode` (int; vlastní pravopis SPA, chybí "g" — reprodukujte doslovně), `rfid`, `max_output_cur` (A), `protect_temp` (°C), `max_input_power`, `allow_charging_time_begin`/`_end` ("HH:mm"), `external_cur_sampling`, `meter_address`, `rate_number`, a `rate{N}_time_begin`/`_end`/`_rate` pro `N` v `1..rate_number` (rozvrh tarifu časového pásma) |
| `POST api/charging/fast` | `mode` (0=přednastavený čas/1=energie/2=náklady), `time_number` (minuty), `time_begintime`, `time_day`, `energy_number` (kWh), `energy_begintime`, `energy_day`, `cost_number`, `cost_begintime`, `cost_day` |
| `POST api/charging/pv` | `import_grid` (0/1), `min_solar_power` (0–22000 W), `boost` (0=vypnuto/1=ruční/2=inteligentní), `manual_energy` (kWh), `start_time`, `stop_time`, `auto_time`, `auto_energy` (kWh) |
| `POST api/charging/off-peak` | `boost` (0/1), `peak_time` (čárkou oddělené 0/1 příznaky, jeden na nakonfigurovaný tarifní slot z `api/charging/basic`), `auto_time`, `auto_energy` (kWh), `balance` (0/1, vyvažování zátěže), `balance_power` (W) |

Pole `*_begintime` používají sentinel `"255:255"` pro "žádný naplánovaný start / nabíjet ihned po připojení" místo skutečného času — nastavuje ho přepínač "připojit a nabíjet" ve webovém formuláři. Vzorové hodnoty v každé fixture (`tests/fixtures/renac_api/charging_{basic,fast,pv,off_peak}.json`) **nejsou z reálného zachyceného provozu** — byly sestaveny z názvů polí a plausibilních výchozích hodnot, ne anonymizovaná reálná data jako všude jinde v tomto dokumentu.

#### Zápis — `POST api/charging/set`

```json
{ "equ_sn": "ABC0123456DEF789", "type": 2, "ids": "max_output_cur", "params": "16" }
```
Odpověď: standardní obálka `{"code": 1, ...}` bez smysluplných `data`. `ids`/`params` jsou paralelní seznamy oddělené čárkou — jedním voláním lze změnit více polí najednou. Čísla musí být formátována stejně, jako by je převedl na řetězec samotný JS (`16`, ne `16.0`) — `RenacApiClient.async_set_charging` to ošetřuje.

Každá hodnota `type` pozorovaná v `setMode()`, kam zapisuje, a stav ověření:

| `type` | Skupina | Pole | Důvěra HA entity |
|---|---|---|---|
| 1 | RFID | `rfid` | Neimplementováno jako entita (citlivé z hlediska bezpečnosti, nízká hodnota) |
| 2 | Základní | `charing_mode`, `max_output_cur`, `protect_temp`, `max_input_power`, `allow_charging_time_begin`/`_end`, `external_cur_sampling`, `meter_address`, `rate{N}_*` | `max_output_cur` implementováno (`number.*_max_current_limit`); `charing_mode`→`select.*_charge_authorization`, `protect_temp`→`number.*_protect_temperature`, `meter_address`→`number.*_meter_address`, `external_cur_sampling`→`select.*_external_current_sampling`, `allow_charging_time_begin`/`_end`→`time.*` vše implementováno. `max_input_power` a rozvrh tarifu `rate{N}_*` **nejsou** implementovány (druhé jmenované potřebuje UI se seznamem slotů, pro které HA nemá čistou vestavěnou entitu) |
| 3 | Celkový režim | `charger_mode` (0=fast/1=pv/2=off_peak) | Implementováno: `select.*_charge_mode` (čte reálné pole `mode` z `api/charging/index`, zapisuje typ=3) |
| 4 | Plán rychlého nabíjení | `mode` (0/1/2) + odpovídající trojice `time_*`/`energy_*`/`cost_*` | `mode`→`select.*_fast_charge_plan`, `energy_number`→`number.*_fast_charge_energy_target`, `cost_number`→`number.*_fast_charge_cost_target`, všechny tři `*_begintime`→`time.*` implementováno. `time_number` (délka trvání, ne čas na hodinách) **není** implementováno |
| 5 | PV/solární boost | `import_grid`, `min_solar_power`, `boost` (0/1/2), + `manual_energy`/`start_time`/`stop_time` (boost=1) nebo `auto_time`/`auto_energy` (boost=2) | Všechna pole implementována napříč `switch.*_pv_allow_grid_import`, `number.*_pv_min_solar_power`, `select.*_pv_boost_mode`, `number.*_pv_manual_boost_energy_target`, `number.*_pv_intelligent_boost_energy_target` a čtyřmi entitami `time.*` |
| 6 | Rozvrh nízkého tarifu **a** vyvažování zátěže (sdílené `type`, rozlišené jen podle `ids`) | Nízký tarif: `boost`, `peak_time`, `auto_time`, `auto_energy`. Vyvažování: `balance`, `balance_power` | `boost`→`switch.*_off_peak_boost`, `auto_time`→`time.*_off_peak_boost_end`, `auto_energy`→`number.*_off_peak_boost_energy_target`, `balance`→`switch.*_load_balance`, `balance_power`→`number.*_load_balance_power` implementováno. `peak_time` (výběr tarifu po slotech, potřebuje rozvrh `rate{N}_*` z typu 2) **není** implementováno |

**Poznámka k částečným zápisům:** SPA vždy odešle celou záložku polí najednou (např. změna PV režimu znovu odešle `import_grid`+`min_solar_power`+`boost`, i když se změnilo jen jedno). Tato integrace místo toho posílá při zápisu z každé entity přesně jedno pole, na základě předpokladu — potvrzeného pouze pro `type 1`/`rfid`, které SPA samo vždy posílá samostatně — že API přijímá částečné sady polí podle `type`. To při testu proti Docker mocku (který jednoduše aplikuje jakákoli `ids` dostane) nebyl problém, ale reálný účet se může chovat jinak; pokud zápis jednoho pole u typu 4/5/6 neprojeví efekt, zkuste `RenacApiClient.async_set_charging()` se všemi poli té záložky najednou.

**Integrace Home Assistant:** viz tabulka souborů v §3 — `number.py`, `select.py`, `switch.py` a `time.py` dohromady implementují 24 entit pro čtení/zápis napříč všemi šesti hodnotami `type`, napojených na nový `RenacSettingsCoordinator` (`coordinator.py`), který dotazuje `api/charging/basic|fast|pv|off-peak` každých 5 minut (`SETTINGS_SCAN_INTERVAL` v `const.py`) — mnohem pomaleji než reálný 30s poll, protože se tyto hodnoty mění zřídka a jde o neověřené zápisové endpointy. Selhání načtení jedné skupiny nastavení se zaloguje a entity té skupiny prostě přejdou do stavu `unavailable`, místo aby zablokovaly nastavení ověřených čtecích senzorů. `max_current_limit`, `select.*_charge_mode` a `switch.*_charging` (2.11) jsou výjimky: čtou z reálného coordinatoru místo toho (rychlejší zpětná vazba po zápisu, a `mode`/`charger_cmd` navíc nejsou součástí žádné odpovědi `charging/basic|fast|pv|off-peak`). **Nic z toho (kromě §2.11) nebylo otestováno na reálném účtu** — udělejte to (začněte něčím nízkorizikovým jako `meter_address` nebo `select`, než čímkoli souvisejícím s proudem/výkonem), než to budete považovat za plně ověřené, a aktualizujte tuto sekci a stavovou tabulku v §1.

### 2.11 `POST api/charging/set` typ=3, `charger_cmd` — start/stop nabíjení ✅ ověřeno naživo

Na rozdíl od všeho v §2.10 tohle **bylo** zachyceno z reálného síťového požadavku: HAR export kliknutí na tlačítka "zapnout"/"vypnout nabíjení" ve webovém portálu (2026-08-03). Je to jediná *zápisová* akce v celém projektu ověřená proti reálnému účtu, ne odvozená z dekompilovaného JS.

Požadavek (start):
```json
{ "equ_sn": "ABC0123456DEF789", "type": 3, "ids": "charger_cmd", "params": 1 }
```
Požadavek (stop): identický s `"params": 2`. Odpověď v obou případech: `{"code": 1, "msg": "0000", "data": null}`.

Dvě věci dělají toto volání výjimečným:
- **`type: 3` je sdílené** mezi tímto a přepnutím celkového režimu (`ids: "charger_mode"`, §2.10) — potvrzuje, že `type` je opravdu jen selektor "jakého druhu příkaz zařízení", ne 1:1 mapování na jedno pole, konzistentně s tím, že `type: 6` je taky sdílený mezi rozvrhem nízkého tarifu a vyvažováním zátěže.
- **`params` je syrové JSON celé číslo** (`1`, ne `"1"`) — každý jiný ověřený zápis `charging/set` v tomto dokumentu posílá `params` jako řetězec spojený čárkami, sestavený obecným diff-a-join kódem formuláře nastavení. Tlačítka start/stop evidentně volají API přímo s doslovným argumentem místo přes tuhle sdílenou cestu kódu. `RenacApiClient.async_set_charger_command()` posílá doslovné celé číslo, aby to odpovídalo; každá jiná zápisová metoda pořád posílá řetězce přes `async_set_charging()`.

V témže HAR záznamu nebyl zachycen navazující požadavek `api/charging/index`, takže výsledný přechod `state2` nebyl přímo pozorován — ale oba požadavky vrátily `code: 1`. **Integrace Home Assistant:** `switch.*_charging` (`switch.py`) — `is_on` odráží skutečně hlášené `state2` wallboxu (nabíjí se vs. ne, `CHARGE_STATES`/`CHARGING_ACTIVE_STATES` v `const.py`), ne jen poslední odeslaný příkaz, takže správně ukáže vypnuto, když pošlete "start" bez připojeného auta. Ověřeno end-to-end proti Docker mock serveru (kompletní cyklus, včetně rozdílu int vs. řetězec u `params`).

---

## 3. Architektura kódu

Kód je v [`custom_components/renac_wallbox/`](../custom_components/renac_wallbox/):

| Soubor | Odpovědnost |
|---|---|
| [`api.py`](../custom_components/renac_wallbox/api.py) | `RenacApiClient` — přihlášení, podepisování požadavků, všechna ověřená volání endpointů |
| [`const.py`](../custom_components/renac_wallbox/const.py) | Doména, základní URL, salt pro podpis, kódy odpovědí, ověřené výčty |
| [`coordinator.py`](../custom_components/renac_wallbox/coordinator.py) | `RenacWallboxCoordinator` dotazuje `api/charging/index` (2.4) každých 30 s (nastavitelné); `RenacSettingsCoordinator` dotazuje `api/charging/basic|fast|pv|off-peak` (2.10) každých 5 minut, best-effort (selhání jedné skupiny neblokuje nastavení) |
| [`config_flow.py`](../custom_components/renac_wallbox/config_flow.py) | UI nastavení: základní URL + e-mail + heslo → výběr stanice → výběr zařízení |
| [`sensor.py`](../custom_components/renac_wallbox/sensor.py) | Jedna entita na ověřené reálné pole (výkon, napětí, proud, energie, náklady, stav, fáze, limit výkonu) |
| [`binary_sensor.py`](../custom_components/renac_wallbox/binary_sensor.py) | Binární senzor `fault` (`state2 == 5`) |
| [`number.py`](../custom_components/renac_wallbox/number.py) | 9 číselných entit pro čtení/zápis: limit max. proudu (napojen na reálný coordinator), ochranná teplota, adresa elektroměru, PV min. solární výkon, cíle energie PV/nízký tarif/rychlé nabíjení, cíl nákladů rychlého nabíjení (vše napojeno na settings, 2.10) |
| [`select.py`](../custom_components/renac_wallbox/select.py) | 5 výčtových entit pro čtení/zápis: celkový režim nabíjení (napojen na reálný coordinator), autorizace nabíjení, externí snímání proudu, režim PV boostu, plán rychlého nabíjení (vše napojeno na settings, 2.10) |
| [`switch.py`](../custom_components/renac_wallbox/switch.py) | ✅ `charging` — start/stop nabíjení (napojeno na reálný coordinator, **ověřeno naživo**, 2.11), plus 3 boolean entity napojené na settings: PV odběr ze sítě, boost v nízkém tarifu, vyvažování zátěže (2.10) |
| [`time.py`](../custom_components/renac_wallbox/time.py) | 9 entit HH:mm pro čtení/zápis: povolené okno nabíjení, časy rozvrhu rychlého/PV/nízkotarifního nabíjení (2.10) |
| [`manifest.json`](../custom_components/renac_wallbox/manifest.json), [`strings.json`](../custom_components/renac_wallbox/strings.json), [`translations/`](../custom_components/renac_wallbox/translations/) | Metadata HA + CZ/EN překlady config flow a entit |

Jeden config entry = jedno zařízení wallbox (`inv_sn`). Pro účty s více wallboxy přidejte integraci vícekrát, jednou na zařízení (config flow vás provede výběrem stanice a zařízení, pokud je jich víc).

Zatím neimplementováno, ponecháno jako budoucí práce: senzor historie relací z bodu 2.7, diagnostika po fázích z bodu 2.8, a další pole/typy `api/charging/set` mimo max. proud (2.10).

---

## 4. Známé mezery / co by měl implementující agent ověřit dále

1. **Jiné regiony než Evropa** — ověřte vzor základní URL pro Asii/Jižní Ameriku (nebo jiný region) na reálném účtu, než to nasadíte pro uživatele mimo EU; v současnosti je nabídnut jen odhadnutý vzor hostname.
2. **`api/charging/set` / `api/charging/basic` (§2.10)** — implementováno a otestováno proti Docker mocku, ale tvar požadavku byl odvozen z dekompilovaného JS, ne z reálného zachyceného provozu. Ověřte to na reálném účtu (ideálně čerstvým HAR záznamem akce Uložit ve formuláři nastavení), než zápisové cestě budete důvěřovat v produkci — zvlášť na hardwaru, kde neočekávaný skok proudu vadí.
3. **Rozsah min/max `max_output_cur`** — `MIN_CURRENT_A`/`MAX_CURRENT_A` v `number.py` (6/32 A) jsou odhad; samotný webový formulář žádné meze nedeklaruje. Nahraďte skutečným podporovaným rozsahem vašeho wallboxu, jakmile ho zjistíte (štítek zařízení nebo instalační dokumentace).
4. **Další `type` u `api/charging/set`** (1=RFID, 3=přepnutí režimu) a další pole `basic` (`protect_temp`, `allow_charging_time_*`, rozvrh tarifu) — názvy polí jsou známé (§2.10), ale nejsou zapojené do žádné HA entity; přirozené další rozšíření, jakmile bude zápisová cesta výše ověřena naživo.
5. **Životnost tokenu / frekvence opětovného přihlášení** — integrace se znovu přihlašuje reaktivně (při `msg == "1000"`), ale skutečná platnost tokenu nebyla změřena; zvažte, zda má smysl přidat proaktivní opětovné přihlášení na časovač, až to bude v praxi pozorováno.
6. **Pole `state` vs. `unit`** — zatím nevysvětlená; pokud zjistíte jejich význam (např. vyvoláním poruchy nebo změnou měny), zapracujte to do `const.py`.

## 4.1 Bezpečnostní poznámky

* Přihlašovací endpoint RENAC přijímá **heslo v čistém textu přes HTTPS** — na klientovi není žádné hashování, které by bylo třeba zachovat. Ukládejte přihlašovací údaje stejně, jako Home Assistant ukládá údaje jakékoli jiné integrace (v config entry, šifrováno na disku, pokud to má HA nastaveno).
* Salt pro podepisování (`SIGN_SALT` v `const.py`) je statický řetězec zabudovaný přímo do veřejného webového klienta RENAC — považovat ho za tajemství by nemělo smysl (posílá se při každém načtení stránky), ale při zveřejnění tohoto projektu jej neprezentujte jako tajemství vašeho vlastního kódu.
* Tato integrace ve stávající podobě provádí pouze **čtecí** operace proti zdokumentovaným, pozorovaným endpointům. Nikdy nezapisuje do `api/charging/set` ani podobných řídicích endpointů.

---

## 5. Testování (bez nutnosti reálných přihlašovacích údajů)

Existují dvě nezávislé vrstvy testů, obě řízené výhradně **anonymizovanými fixture daty s reálným tvarem** odvozenými z původního HAR záznamu (`tests/fixtures/renac_api/*.json` — stejné fiktivní hodnoty jako v příkladech v §2). Ani jedna vrstva nikdy nekontaktuje reálný cloud RENAC a nepotřebuje reálný e-mail/heslo/token.

**1. Unit testy** (`tests/test_api.py`) — spustí dočasný in-process `aiohttp` server, který přehrává fixtures a nezávisle si sám ověřuje hlavičky `Token`/`timestamp`/`sign`, takže testy selžou, pokud se logika podepisování v `api.py` někdy rozejde s reálným schématem:
```bash
pip install -r tests/requirements-test.txt
pytest tests/test_api.py -v
```

**2. Kompletní end-to-end test celé HACS integrace v Dockeru** (`docker-compose.test.yml`) — spustí skutečný kontejner s Home Assistant core, do kterého je `custom_components/renac_wallbox` připojen přesně tak, jak by ho nainstaloval HACS, spolu s malým mock RENAC API kontejnerem (`tests/mock_server/`), který servíruje stejná fixture data přes HTTP a vynucuje reálné schéma podepisování. Tím se otestuje *skutečný* config flow, coordinator i entity platformy uvnitř běžícího HA — během vývoje to odhalilo dvě reálné chyby (neplatná kombinace `state_class`/`device_class` u senzoru energie relace, a obyčejný řetězec předaný tam, kde HA očekává enum `EntityCategory` u tří diagnostických senzorů — obojí je nyní opraveno v `sensor.py`).

```bash
docker compose -f docker-compose.test.yml up --build -d
# počkejte ~10 s, než Home Assistant nastartuje, pak dokončete onboarding
# a config flow proti mock serveru (http://mock-renac-api:8084) přes REST
# API Home Assistant, nebo to projeďte přes UI na http://localhost:18123
# s libovolným e-mailem/heslem (mock přijme cokoli) a základní URL
# http://mock-renac-api:8084.
docker compose -f docker-compose.test.yml down
```
Očekávejte, že se pod `/api/states` objeví `sensor.wallbox_..._power`, `..._voltage`, `..._state` (`idle`), `..._charge_mode` (`pv`) atd., odpovídající hodnotám polí zdokumentovaným v §2.4.
