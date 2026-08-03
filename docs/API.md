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
| `api/charging/basic` (read settings incl. max current) | ⚠️ Derived from decompiled JS (exact request-building code, not a guessed shape), not live-captured — see §2.10 |
| `api/charging/set` type=2 (write max current + other settings) | ⚠️ Implemented (`number.*_max_current_limit`), derived from decompiled JS, tested against the Docker mock server but not yet a real account — see §2.10 |
| Home Assistant integration (`custom_components/renac_wallbox/`) | ✅ Read path tested end-to-end against a real RENAC EV-AC3P-11K wallbox via the full HACS install flow; the new write path (max current) is Docker-mock-tested only, not yet live (see §5) |
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

### 2.10 `POST api/charging/basic` (read) and `POST api/charging/set` type=2 (write) — wallbox settings, incl. max current ⚠️ derived from decompiled JS, not live-captured

Unlike every other endpoint in this document, these two were **not** confirmed by watching a real network request — the setting-change action isn't reachable in the web portal without navigating to a specific device-settings view that a fresh account/session doesn't land on by default, and no HAR of it exists yet. Instead, the exact request-building code was located and read directly: the settings form component (`chunk-184c83ca`, module `fb3b`, decompiled — not the component name itself, which isn't retained by the minifier) binds an `el-input-number` labeled "Max output current (A)" to `basic.max_output_cur`, and its Save button's `setMode(2)` handler diffs the form against the last-read snapshot and submits exactly the changed field names/values. This is stronger evidence than a guessed URL+params shape (it's the literal code that builds the request), but it has not been exercised against the real API — **test carefully, on a wallbox where an unexpected current limit isn't a safety problem, before relying on this.**

**Read** — `POST api/charging/basic`:
```json
{ "inv_sn": "ABC0123456DEF789" }
```
Response (`data`), field names read directly from the `readBasic()` method (`Object(o["X"])(...)`, where export `"X"` is bound to the same `api/charging/basic` wrapper function found via static analysis, same technique as §2.5's `bg/equList` correction):
```json
{
  "charing_mode": 1,
  "rfid": "",
  "max_output_cur": 7,
  "protect_temp": 85,
  "max_input_power": 22000,
  "allow_charging_time_begin": "00:00",
  "allow_charging_time_end": "23:59",
  "external_cur_sampling": 0,
  "meter_address": 1,
  "rate_number": 0
}
```
Note `charing_mode` is the SPA's own spelling (missing a "g") — reproduce it verbatim, it is almost certainly what the server expects. `rate_number` indicates how many time-of-use tariff entries follow as `rate{N}_time_begin` / `rate{N}_time_end` / `rate{N}_rate` for `N` in `1..rate_number` (not shown above since this sample has none configured). The sample values above are **not from a live capture** — they were constructed from the field names and plausible defaults, not sanitized real data like everywhere else in this document.

**Write** — `POST api/charging/set`:
```json
{ "equ_sn": "ABC0123456DEF789", "type": 2, "ids": "max_output_cur", "params": "16" }
```
Response: the standard `{"code": 1, ...}` envelope with no meaningful `data`.

`ids` and `params` are parallel comma-joined lists — multiple fields can be changed in one call, e.g. `"ids": "max_output_cur,protect_temp", "params": "16,90"`. Only include fields that actually changed (this mirrors what the SPA itself does, via a diff against the last `readBasic()` snapshot — not confirmed to be a hard requirement, but safest to follow). Numbers must be formatted the way JS's own number-to-string conversion would (`16`, not `16.0`) — `RenacApiClient.async_set_charging_basic` handles this.

Two other `type` values were also observed in the same `setMode()` method, for completeness (**not implemented, not live-tested**):
- `type: 1` — RFID card change: `{"equ_sn": "...", "type": 1, "ids": "rfid", "params": "<card id>"}`.
- `type: 3` — switch which charging-mode tab is active (fast/PV/off-peak): `{"equ_sn": "...", "type": 3, "ids": "charger_mode", "params": "<0|1|2>"}`, matching the `mode` enum in §2.4/const.py.

Other `basic` fields that appear settable via `type: 2` alongside `max_output_cur`, per the same diffing code, but not exposed as HA entities yet: `charing_mode`, `protect_temp`, `max_input_power`, `allow_charging_time_begin`/`_end`, `external_cur_sampling`, `meter_address`, and the `rate{N}_*` time-of-use tariff schedule.

**Home Assistant integration:** `number.<device>_max_current_limit` (`custom_components/renac_wallbox/number.py`) reads/writes `max_output_cur` through `RenacApiClient.async_set_max_current()`. Min/max bounds (6–32 A) are a conservative guess, not a RENAC-confirmed hardware range — adjust `MIN_CURRENT_A`/`MAX_CURRENT_A` in `number.py` if your device's real range differs. Verified end-to-end against the Docker mock server (round trip: set value → `api/charging/set` call with the exact payload above → mock reflects it → coordinator refresh → entity shows new value), but **not yet against a real account** — do that before treating this as fully confirmed, and update this section (and §1's status table) once you have.

---

## 3. Code architecture

Code lives in [`custom_components/renac_wallbox/`](../custom_components/renac_wallbox/):

| File | Responsibility |
|---|---|
| [`api.py`](../custom_components/renac_wallbox/api.py) | `RenacApiClient` — login, request signing, all confirmed endpoint calls |
| [`const.py`](../custom_components/renac_wallbox/const.py) | Domain, base URL, signing salt, response codes, confirmed enums |
| [`coordinator.py`](../custom_components/renac_wallbox/coordinator.py) | `DataUpdateCoordinator` polling `api/charging/index` (2.4) every 30s (configurable) |
| [`config_flow.py`](../custom_components/renac_wallbox/config_flow.py) | UI setup: base URL + email + password → pick station → pick device |
| [`sensor.py`](../custom_components/renac_wallbox/sensor.py) | One entity per confirmed field (power, voltage, current, energy, cost, state, mode, phase, limits) |
| [`binary_sensor.py`](../custom_components/renac_wallbox/binary_sensor.py) | `fault` binary sensor (`state2 == 5`) |
| [`number.py`](../custom_components/renac_wallbox/number.py) | `max_current_limit` — read/write `max_output_cur` via `api/charging/basic` / `api/charging/set` (2.10); ⚠️ write path not yet live-tested |
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
| `api/charging/basic` (čtení nastavení vč. max. proudu) | ⚠️ Odvozeno z dekompilovaného JS (skutečný kód sestavující požadavek, ne odhad tvaru), nezachyceno naživo — viz §2.10 |
| `api/charging/set` typ=2 (zápis max. proudu a dalších nastavení) | ⚠️ Implementováno (`number.*_max_current_limit`), odvozeno z dekompilovaného JS, otestováno proti Docker mock serveru, zatím ne na reálném účtu — viz §2.10 |
| Integrace Home Assistant (`custom_components/renac_wallbox/`) | ✅ Čtecí část otestována end-to-end na reálném wallboxu RENAC EV-AC3P-11K přes celý instalační postup HACS; nová zápisová část (max. proud) zatím jen v Docker mocku, ne naživo (viz §5) |
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

### 2.10 `POST api/charging/basic` (čtení) a `POST api/charging/set` typ=2 (zápis) — nastavení wallboxu vč. max. proudu ⚠️ odvozeno z dekompilovaného JS, nezachyceno naživo

Na rozdíl od každého jiného endpointu v tomto dokumentu tyto dva **nebyly** potvrzeny sledováním reálného síťového požadavku — akce změny nastavení není ve webovém portálu dosažitelná bez navigace do konkrétní obrazovky nastavení zařízení, na kterou čerstvý účet/relace defaultně nedojde, a HAR záznam takové akce zatím neexistuje. Místo toho byl přímo dohledán a přečten skutečný kód sestavující požadavek: komponenta formuláře nastavení (`chunk-184c83ca`, modul `fb3b`, dekompilováno — název samotné komponenty minifikátor nezachovává) navazuje `el-input-number` s popiskem "Max output current (A)" na `basic.max_output_cur`, a handler `setMode(2)` jejího tlačítka Uložit porovná formulář s posledně načteným stavem a odešle přesně jen změněné názvy polí/hodnoty. To je silnější důkaz než odhadnutý tvar URL+parametrů (jde o doslovný kód, který požadavek sestavuje), ale nebylo to vyzkoušeno proti reálnému API — **než se na to spolehnete, otestujte to opatrně, na wallboxu, kde neočekávaný limit proudu není bezpečnostní problém.**

**Čtení** — `POST api/charging/basic`:
```json
{ "inv_sn": "ABC0123456DEF789" }
```
Odpověď (`data`), názvy polí přečtené přímo z metody `readBasic()` (`Object(o["X"])(...)`, kde export `"X"` je navázán na stejnou wrapper funkci `api/charging/basic`, nalezenou stejnou technikou statické analýzy jako oprava `bg/equList` v §2.5):
```json
{
  "charing_mode": 1,
  "rfid": "",
  "max_output_cur": 7,
  "protect_temp": 85,
  "max_input_power": 22000,
  "allow_charging_time_begin": "00:00",
  "allow_charging_time_end": "23:59",
  "external_cur_sampling": 0,
  "meter_address": 1,
  "rate_number": 0
}
```
Všimněte si, že `charing_mode` je vlastní pravopis SPA (chybí "g") — reprodukujte to doslovně, téměř jistě je to přesně to, co server očekává. `rate_number` udává, kolik položek tarifu časového pásma následuje jako `rate{N}_time_begin` / `rate{N}_time_end` / `rate{N}_rate` pro `N` v rozsahu `1..rate_number` (výše nejsou zobrazeny, protože tento vzorek žádné nemá nastavené). Hodnoty výše **nejsou z reálného zachyceného provozu** — byly sestaveny z názvů polí a plausibilních výchozích hodnot, ne anonymizovaná reálná data jako všude jinde v tomto dokumentu.

**Zápis** — `POST api/charging/set`:
```json
{ "equ_sn": "ABC0123456DEF789", "type": 2, "ids": "max_output_cur", "params": "16" }
```
Odpověď: standardní obálka `{"code": 1, ...}` bez smysluplných `data`.

`ids` a `params` jsou paralelní seznamy oddělené čárkou — jedním voláním lze změnit více polí najednou, např. `"ids": "max_output_cur,protect_temp", "params": "16,90"`. Zahrnujte pouze pole, která se skutečně změnila (tak to dělá i SPA samo, porovnáním proti poslednímu stavu z `readBasic()` — nepotvrzeno jako tvrdý požadavek, ale nejbezpečnější to dodržet). Čísla musí být formátována stejně, jako by je převedl na řetězec samotný JS (`16`, ne `16.0`) — `RenacApiClient.async_set_charging_basic` to ošetřuje.

V téže metodě `setMode()` byly pro úplnost pozorovány i dvě další hodnoty `type` (**neimplementováno, netestováno naživo**):
- `type: 1` — změna RFID karty: `{"equ_sn": "...", "type": 1, "ids": "rfid", "params": "<číslo karty>"}`.
- `type: 3` — přepnutí aktivní záložky režimu nabíjení (rychlé/PV/nízký tarif): `{"equ_sn": "...", "type": 3, "ids": "charger_mode", "params": "<0|1|2>"}`, odpovídá výčtu `mode` z §2.4/const.py.

Další pole `basic`, která se zdají být nastavitelná přes `type: 2` spolu s `max_output_cur`, podle stejného diffovacího kódu, ale zatím nejsou vystavena jako HA entity: `charing_mode`, `protect_temp`, `max_input_power`, `allow_charging_time_begin`/`_end`, `external_cur_sampling`, `meter_address` a rozvrh tarifu `rate{N}_*`.

**Integrace Home Assistant:** `number.<zařízení>_max_current_limit` (`custom_components/renac_wallbox/number.py`) čte/zapisuje `max_output_cur` přes `RenacApiClient.async_set_max_current()`. Meze min/max (6–32 A) jsou konzervativní odhad, ne RENAC-potvrzený hardwarový rozsah — upravte `MIN_CURRENT_A`/`MAX_CURRENT_A` v `number.py`, pokud se reálný rozsah vašeho zařízení liší. Ověřeno end-to-end proti Docker mock serveru (celý cyklus: nastavení hodnoty → volání `api/charging/set` s přesně výše uvedeným payloadem → mock to odrazí zpět → obnovení coordinatoru → entita ukáže novou hodnotu), ale **zatím ne proti reálnému účtu** — udělejte to, než to budete považovat za plně ověřené, a aktualizujte tuto sekci (a stavovou tabulku v §1).

---

## 3. Architektura kódu

Kód je v [`custom_components/renac_wallbox/`](../custom_components/renac_wallbox/):

| Soubor | Odpovědnost |
|---|---|
| [`api.py`](../custom_components/renac_wallbox/api.py) | `RenacApiClient` — přihlášení, podepisování požadavků, všechna ověřená volání endpointů |
| [`const.py`](../custom_components/renac_wallbox/const.py) | Doména, základní URL, salt pro podpis, kódy odpovědí, ověřené výčty |
| [`coordinator.py`](../custom_components/renac_wallbox/coordinator.py) | `DataUpdateCoordinator` dotazující `api/charging/index` (2.4) každých 30 s (nastavitelné) |
| [`config_flow.py`](../custom_components/renac_wallbox/config_flow.py) | UI nastavení: základní URL + e-mail + heslo → výběr stanice → výběr zařízení |
| [`sensor.py`](../custom_components/renac_wallbox/sensor.py) | Jedna entita na ověřené pole (výkon, napětí, proud, energie, náklady, stav, režim, fáze, limity) |
| [`binary_sensor.py`](../custom_components/renac_wallbox/binary_sensor.py) | Binární senzor `fault` (`state2 == 5`) |
| [`number.py`](../custom_components/renac_wallbox/number.py) | `max_current_limit` — čtení/zápis `max_output_cur` přes `api/charging/basic` / `api/charging/set` (2.10); ⚠️ zápisová cesta zatím netestována naživo |
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
