# RENAC Wallbox — Home Assistant Integration

> [!CAUTION]
> **⛔ 100% AI-GENERATED / "VIBE-CODED" — NOT REVIEWED BY A PROFESSIONAL DEVELOPER. USE ENTIRELY AT YOUR OWN RISK. ⛔**
> Every line of code, every API endpoint, and this entire README were produced by an AI coding agent through reverse engineering of a closed, undocumented cloud API — no human software engineer has audited this code for correctness or safety. It reads (and, if you extend it, could write) data related to your home's electrical/EV-charging equipment through your real RENAC account credentials. There is **no warranty of any kind** and the author accepts **no liability whatsoever** for any damage, data loss, account lockout, incorrect readings, or electrical/hardware issues arising from using this project. See [LICENSE](LICENSE). If that's not acceptable to you, don't use this.

Custom Home Assistant integration that reads live telemetry from a **RENAC AC wallbox** (EV charger) via the RENAC cloud portal at `https://seceu.renacpower.com` (and its regional siblings). No local/LAN API exists for these devices — everything goes through RENAC's cloud, so this integration talks to the same backend the web portal uses.

This document is written to be **directly actionable by a coding agent** (or a human) picking up this repository: it separates what was **confirmed against a real device** from what is **inferred from source and not yet verified**, and gives exact request/response payloads.

> 🇨🇿 Návod k instalaci a česká verze dokumentace jsou níže, za anglickou. / 🇬🇧 English installation guide and documentation first, Czech version below.

---

## 0. Install via HACS (start here)

This repository is a valid **HACS custom repository** (see [`hacs.json`](hacs.json)).

1. In Home Assistant, open **HACS**.
2. Go to **Integrations**, click the **⋮** menu (top right) → **Custom repositories**.
3. Add:
   - **Repository:** `https://github.com/ondrej1808/HA_renac_inverter_api`
   - **Category:** `Integration`
   - Click **Add**.
4. Find **"RENAC Wallbox"** in HACS (search for it, or it will appear under *New* on the HACS Integrations dashboard) and click **Download**.
5. **Restart Home Assistant** (Settings → System → Restart) — required for HA to pick up the new `custom_components/renac_wallbox/` folder.
6. Go to **Settings → Devices & Services → Add Integration**, search for **"RENAC Wallbox"**.
7. Enter the **API base URL** (leave the default for the Europe region unless you know you need a different one — see §3.4), and the **same email/password you use to log in at seceu.renacpower.com**.
8. If your account has more than one wallbox station, pick the one you want. If that station has more than one device, pick its serial number.
9. Done — entities appear under one device per wallbox. Repeat step 6–8 once per additional wallbox if you have more than one.

**Credentials handling:** your email/password are stored only inside Home Assistant's own config-entry storage (the same mechanism every other HA integration uses) and are sent only to the RENAC cloud API (`api/user/login`) over HTTPS, exactly like the official RENAC web portal does. They are never sent anywhere else, never logged, and never included in this repository, its README, or any file committed here.

*(Manual, non-HACS installation is also possible — see §3.1.)*

---

## 1. Status

| Piece | Status |
|---|---|
| Auth (login, token signing) | ✅ Confirmed against a live account |
| `api/station/list` | ✅ Confirmed (live capture) |
| `api/charging/index` (single device, `{inv_sn}`) | ✅ Confirmed (live capture) — **this is the "read all wallbox data" call** |
| `api/charging/index` (device discovery, `{station_id,user_id,...}`) | ⚠️ Inferred from minified JS, not captured live |
| `api/station/equipStat` | ✅ Confirmed (live capture) |
| `api/charging/equ/charging_record` (session history) | ✅ Confirmed (live capture) |
| `api/charging/equ/detailChart` (time-series history) | ✅ Confirmed (live capture) |
| `api/charging/set` (writing mode / current limit) | ❌ Not implemented, endpoint exists but payload unconfirmed |
| Home Assistant integration (`custom_components/renac_wallbox/`) | ✅ Implemented, sensors + binary_sensor, config flow, not yet tested inside a running HA instance |
| Regions other than Europe | ⚠️ Base URL pattern guessed, unverified |

**How this was reverse engineered:** the RENAC web portal is a Vue.js SPA. Its production JS bundles (`app.*.js` + chunk files) were fetched and searched directly (no login required to read the client code) for API route strings, the axios request/response interceptors, and the login form logic. This gave the auth scheme and most endpoint paths/params. A **HAR capture of a real authenticated browser session against a real wallbox** was then used to confirm exact request/response JSON shapes for the endpoints marked ✅ above. **All identifying values from that capture (token, user id, device serial, station id, station name, owner name, installer name) were replaced with fake placeholders before anything was written to this repository** — only the field *names* and realistic *shapes/value types* are real. The token itself was never written to disk outside the original local HAR file, and is not present anywhere in this repository or its history.

**Prior art / cross-checked against:**
- The official **"RENAC SEC API Documentation" v2.0.7** (a partner/open-platform PDF circulated on the [ioBroker forum](https://forum.iobroker.net/)) independently documents `api/user/login` and `api/station/list` with the exact same parameter and response-field names found here — this confirms those two endpoints rather than relying on the JS reverse-engineering alone. That document targets a different default host (`153.le-pv.com:8082`, no HTTPS, no signing headers) and **does not mention any wallbox/EV-charging endpoint, nor the `Token`/`timestamp`/`sign` header scheme** used by the production web portal — the charging-pile endpoints and the request-signing scheme documented in §2 of this README are original findings from this project, not copied from that document.
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

### 2.5 `POST api/charging/index` — device discovery (⚠️ inferred, not captured live)

Reconstructed from the SPA's `getPileIndex()` method. The *same URL* apparently branches on which parameters are supplied:

Request:
```json
{ "user_id": 100001, "station_id": 200001, "status": 0, "offset": 0, "rows": 10 }
```
Expected response shape (unverified):
```json
{ "total": 1, "list": [ { "INV_SN": "ABC0123456DEF789", "...": "..." } ] }
```
Used to resolve a station's device serial (`INV_SN`) the first time, before switching to the confirmed single-device call in 2.4 for polling. **Verify this against your own account before relying on it** — if it doesn't behave as expected, the fallback in the shipped integration is to use `equ_sn` off the station object, or to prompt the user for the serial manually during config flow.

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

Extracted from the JS route table, listed for completeness / future extension: `api/station/weather`, `api/charging/basic`, `api/charging/fast`, `api/charging/pv`, `api/charging/off-peak`, `api/charging/set` (writes — mode/limit changes, payload not captured), `api/charging/equ/detail`, `api/charging/equ/detailChart/export`, `api/user/info`, `api/user/changePwd`, `api/com/getWebVer`. If you need write control (start/stop, change `max_cur`, switch `mode`), start by capturing a real browser session performing that action (DevTools → Network, or the same HAR-capture approach used here) rather than guessing the payload.

---

## 3. Home Assistant integration

Code lives in [`custom_components/renac_wallbox/`](custom_components/renac_wallbox/):

| File | Responsibility |
|---|---|
| [`api.py`](custom_components/renac_wallbox/api.py) | `RenacApiClient` — login, request signing, all confirmed endpoint calls |
| [`const.py`](custom_components/renac_wallbox/const.py) | Domain, base URL, signing salt, response codes, confirmed enums |
| [`coordinator.py`](custom_components/renac_wallbox/coordinator.py) | `DataUpdateCoordinator` polling `api/charging/index` (2.4) every 30s (configurable) |
| [`config_flow.py`](custom_components/renac_wallbox/config_flow.py) | UI setup: base URL + email + password → pick station → pick device |
| [`sensor.py`](custom_components/renac_wallbox/sensor.py) | One entity per confirmed field (power, voltage, current, energy, cost, state, mode, phase, limits) |
| [`binary_sensor.py`](custom_components/renac_wallbox/binary_sensor.py) | `fault` binary sensor (`state2 == 5`) |
| [`manifest.json`](custom_components/renac_wallbox/manifest.json), [`strings.json`](custom_components/renac_wallbox/strings.json), [`translations/`](custom_components/renac_wallbox/translations/) | HA metadata + EN/CZ config-flow and entity translations |

One config entry = one wallbox device (`inv_sn`). Multi-wallbox accounts add the integration once per device (the config flow walks you through picking the station and device if there is more than one).

### 3.1 Installation

The recommended path is **HACS**, covered step by step in §0 above. Manual installation without HACS also works:
1. Copy `custom_components/renac_wallbox/` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Settings → Devices & Services → Add Integration → search "RENAC Wallbox".

### 3.2 Config flow

1. Enter API base URL (defaults to the confirmed Europe endpoint), email, password — same credentials as `seceu.renacpower.com`.
2. If the account has more than one wallbox station, pick one.
3. If that station has more than one device, pick a serial number.
4. Entities are created under one device per `inv_sn`.

Polling interval defaults to 30s and can be changed afterwards via the integration's **Configure** (options flow), 10–3600s.

### 3.3 What you get

Sensors: power (W), voltage (V), current (A), total energy (kWh, `total_increasing`), session energy (kWh), total cost, session cost, session duration, state (`idle`/`plugged_in`/`charging`/`fault`), mode (`fast`/`pv`/`off_peak`), phase (`single_phase`/`three_phase`), max current limit, max power limit, PV minimum solar power threshold (diagnostic). Plus a `problem` binary sensor for fault state.

Not yet implemented, left as future work: session-history sensor from 2.7, per-phase diagnostics from 2.8, and any write/control entities against `api/charging/set` (2.9) since its request payload has not been confirmed against a live account.

### 3.4 Known gaps / what an implementing agent should verify next

1. **Regions other than Europe** — confirm the base URL pattern for Asia/South America (or any other region) against a real account before shipping to non-EU users; currently only a guessed hostname pattern is offered.
2. **Device-discovery call (2.5)** — not captured live; if it doesn't return the expected `list[].INV_SN` shape, the config flow's device-picker step will need adjusting.
3. **`api/charging/set`** — capture a real "change charging mode" or "change current limit" action from the web portal (browser DevTools Network tab, or export a HAR like the one used for this document) before adding number/select control entities.
4. **Token lifetime / re-login cadence** — the integration re-logs in reactively (on `msg == "1000"`), but the actual TTL of a token was not measured; consider whether a proactive re-login on a timer is worth adding once observed in practice.
5. **`state` vs `unit` fields** — currently unexplained; if you find their meaning (e.g. by triggering a fault or changing currency), fold it into `const.py`.

### 3.5 Security notes

* The RENAC login endpoint accepts a **plaintext password over HTTPS** — there is no client-side hashing to preserve. Store credentials the same way Home Assistant stores any other integration's credentials (in the config entry, encrypted at rest by HA's storage if configured).
* The signing salt (`SIGN_SALT` in `const.py`) is a static string baked into RENAC's own public web client — treating it as a secret would be pointless (it ships in every page load), but do not present it as *your* code's secret if this project is published.
* This integration only performs **read** operations against documented, observed endpoints. It never writes to `api/charging/set` or similar control endpoints as shipped.

### 3.6 Testing (no real credentials required)

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
# HA's own REST API — see the walkthrough in the PR/commit history for
# the exact curl sequence, or drive it through the UI at
# http://localhost:18123 with any email/password (the mock accepts
# anything) and base URL http://mock-renac-api:8084.
docker compose -f docker-compose.test.yml down
```
Expect to see `sensor.wallbox_..._power`, `..._voltage`, `..._state` (`idle`), `..._charge_mode` (`pv`), etc. appear under `/api/states`, matching the field values documented in §2.4.

---
---

# 🇨🇿 Wallbox RENAC — integrace pro Home Assistant

> [!CAUTION]
> **⛔ 100 % VYGENEROVÁNO AI / "VIBE-CODED" — NEZKONTROLOVÁNO PROFESIONÁLNÍM VÝVOJÁŘEM. POUŽÍVÁTE ZCELA NA VLASTNÍ RIZIKO. ⛔**
> Každý řádek kódu, každý API endpoint i celé toto README vytvořil AI agent reverzním inženýrstvím uzavřeného, nedokumentovaného cloudového API — žádný člověk-vývojář tento kód neauditoval z hlediska správnosti ani bezpečnosti. Čte (a pokud si ho rozšíříte, mohl by i zapisovat) data týkající se elektrického/EV-nabíjecího zařízení ve vaší domácnosti, a to pomocí vašich skutečných přihlašovacích údajů k účtu RENAC. Nejsou poskytovány **žádné záruky** a autor **nenese žádnou odpovědnost** za jakoukoli škodu, ztrátu dat, zablokování účtu, nesprávná čtení nebo elektrické/hardwarové problémy vzniklé používáním tohoto projektu. Viz [LICENSE](LICENSE). Pokud to pro vás není přijatelné, tento projekt nepoužívejte.

Vlastní (custom) integrace pro Home Assistant, která čte živá data z **AC wallboxu RENAC** (nabíječky pro elektromobily) přes cloudový portál RENAC na `https://seceu.renacpower.com` (a jeho regionální varianty). Tato zařízení nemají žádné lokální/LAN API — vše jde přes cloud RENAC, takže integrace komunikuje se stejným backendem jako webový portál.

Tento dokument je psán tak, aby byl **přímo použitelný pro agenta (AI nebo člověka)**, který na projektu bude pokračovat: odděluje, co bylo **ověřeno na reálném zařízení**, od toho, co je **odvozeno ze zdrojového kódu a zatím neověřeno**, a uvádí přesné požadavky/odpovědi API.

## 0. Instalace přes HACS (začněte zde)

Tento repozitář je platný **vlastní (custom) repozitář HACS** (viz [`hacs.json`](hacs.json)).

1. V Home Assistant otevřete **HACS**.
2. Přejděte na **Integrations**, klikněte na nabídku **⋮** (vpravo nahoře) → **Custom repositories**.
3. Přidejte:
   - **Repository:** `https://github.com/ondrej1808/HA_renac_inverter_api`
   - **Category:** `Integration`
   - Klikněte na **Add**.
4. Najděte **"RENAC Wallbox"** v HACS (vyhledejte ho, nebo se objeví v sekci *New* na dashboardu HACS Integrations) a klikněte na **Download**.
5. **Restartujte Home Assistant** (Nastavení → Systém → Restartovat) — nutné, aby HA načetl novou složku `custom_components/renac_wallbox/`.
6. Přejděte na **Nastavení → Zařízení a služby → Přidat integraci**, vyhledejte **"RENAC Wallbox"**.
7. Zadejte **základní URL API** (ponechte výchozí pro region Evropa, pokud si nejste jisti, že potřebujete jinou — viz §3.4) a **stejný e-mail/heslo, jaké používáte pro přihlášení na seceu.renacpower.com**.
8. Pokud má váš účet více wallbox stanic, vyberte tu správnou. Pokud má daná stanice více zařízení, vyberte jeho sériové číslo.
9. Hotovo — entity se objeví pod jedním zařízením na wallbox. Pro každý další wallbox opakujte kroky 6–8.

**Zacházení s přihlašovacími údaji:** váš e-mail/heslo se ukládají pouze v rámci vlastního úložiště config entry Home Assistant (stejný mechanismus jako u každé jiné integrace HA) a odesílají se pouze do cloudového API RENAC (`api/user/login`) přes HTTPS — přesně tak, jak to dělá i oficiální webový portál RENAC. Nikam jinam se neposílají, nikde se nelogují a nejsou nikde součástí tohoto repozitáře, jeho README ani žádného zde uloženého souboru.

*(Ruční instalace bez HACS je také možná — viz §3.1.)*

## 1. Stav

| Část | Stav |
|---|---|
| Autentizace (přihlášení, podepisování tokenu) | ✅ Ověřeno na reálném účtu |
| `api/station/list` | ✅ Ověřeno (reálný zachycený provoz) |
| `api/charging/index` (jedno zařízení, `{inv_sn}`) | ✅ Ověřeno (reálný zachycený provoz) — **toto je volání pro "vyčtení všech dat wallboxu"** |
| `api/charging/index` (vyhledání zařízení, `{station_id,user_id,...}`) | ⚠️ Odvozeno z minifikovaného JS, není ověřeno na reálném provozu |
| `api/station/equipStat` | ✅ Ověřeno (reálný zachycený provoz) |
| `api/charging/equ/charging_record` (historie nabíjecích relací) | ✅ Ověřeno (reálný zachycený provoz) |
| `api/charging/equ/detailChart` (časová řada historie) | ✅ Ověřeno (reálný zachycený provoz) |
| `api/charging/set` (zápis režimu / limitu proudu) | ❌ Neimplementováno, endpoint existuje, ale formát požadavku neznámý |
| Integrace Home Assistant (`custom_components/renac_wallbox/`) | ✅ Implementováno (senzory + binary_sensor, config flow), zatím netestováno v běžícím HA |
| Jiné regiony než Evropa | ⚠️ Vzor základní URL je pouze odhadnut, neověřeno |

**Jak bylo API zjištěno:** webový portál RENAC je Vue.js SPA. Jeho produkční JS balíčky (`app.*.js` a chunk soubory) byly staženy a prohledány přímo (bez nutnosti přihlášení, jde o veřejný klientský kód) na řetězce API cest, axios request/response interceptory a logiku přihlašovacího formuláře. Tím se získalo autentizační schéma a většina cest/parametrů endpointů. Následně byl použit **HAR záznam reálné přihlášené relace prohlížeče proti skutečnému wallboxu** k ověření přesných tvarů JSON požadavků/odpovědí u endpointů označených ✅ výše. **Všechny identifikační hodnoty z tohoto záznamu (token, ID uživatele, sériové číslo zařízení, ID stanice, název stanice, jméno majitele, jméno instalatéra) byly před zápisem do tohoto repozitáře nahrazeny fiktivními hodnotami** — reálné jsou pouze *názvy* polí a realistické *tvary/typy* dat. Samotný token nebyl nikdy zapsán mimo původní lokální HAR soubor a v tomto repozitáři ani jeho historii se nikde nenachází.

**Předchozí práce / křížová kontrola oproti:**
- Oficiální **"RENAC SEC API Documentation" v2.0.7** (partnerské/open-platform PDF šířené na [fóru ioBroker](https://forum.iobroker.net/)) nezávisle dokumentuje `api/user/login` a `api/station/list` se zcela stejnými názvy parametrů a polí odpovědi, jaké byly nalezeny zde — to potvrzuje tyto dva endpointy nezávisle na samotném reverzním inženýrství z JS. Tento dokument cílí na jiný výchozí hostitel (`153.le-pv.com:8082`, bez HTTPS, bez podepisovacích hlaviček) a **vůbec nezmiňuje žádný endpoint pro wallbox/nabíjení EV, ani schéma hlaviček `Token`/`timestamp`/`sign`** používané produkčním webovým portálem — endpointy pro nabíjecí stanice a schéma podepisování požadavků popsané v §2 tohoto README jsou původní zjištění tohoto projektu, nikoli převzatá z onoho dokumentu.
- [`raschy/ioBroker.renacidc`](https://github.com/raschy/ioBroker.renacidc), nezávislý ioBroker adaptér pro **solární střídače** RENAC (ne wallboxy), uvádí v changelogu záznam o "speciálním API podpisu", který si musel sám reverzně odvodit — což potvrzuje, že cloud RENAC skutečně vyžaduje vlastní podepisování požadavků nad rámec toho, co dokumentuje oficiální PDF, aniž by byl zdrojový kód onoho projektu zde konzultován či kopírován.
- [`gastush/ha-renac`](https://github.com/gastush/ha-renac) a [`HA1Andrzej/RENAC-MODBUS`](https://github.com/HA1Andrzej/RENAC-MODBUS) jsou existující integrace Home Assistant pro **hybridní/on-grid solární střídače** RENAC přes lokální Modbus/RS485 — zcela odlišný přenosový kanál (LAN, ne cloud) a produktová řada oproti AC wallboxu popsanému zde. Žádný překryv v kódu ani endpointech.

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

### 2.5 `POST api/charging/index` — vyhledání zařízení (⚠️ odvozeno, není ověřeno naživo)

Rekonstruováno z metody `getPileIndex()` v SPA. Zdá se, že *stejná URL* se chová jinak podle toho, jaké parametry dostane:

Požadavek:
```json
{ "user_id": 100001, "station_id": 200001, "status": 0, "offset": 0, "rows": 10 }
```
Očekávaný tvar odpovědi (neověřeno):
```json
{ "total": 1, "list": [ { "INV_SN": "ABC0123456DEF789", "...": "..." } ] }
```
Používá se k prvotnímu zjištění sériového čísla zařízení (`INV_SN`) dané stanice, než se přejde na ověřené volání pro jedno zařízení z bodu 2.4 pro pravidelné dotazování. **Ověřte to na vlastním účtu, než se na to spolehnete** — pokud se chování neshoduje s očekáváním, náhradní řešení v dodané integraci je použít `equ_sn` přímo z objektu stanice, nebo nechat uživatele zadat sériové číslo ručně v config flow.

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

Extrahováno z tabulky rout v JS, uvedeno pro úplnost / budoucí rozšíření: `api/station/weather`, `api/charging/basic`, `api/charging/fast`, `api/charging/pv`, `api/charging/off-peak`, `api/charging/set` (zápisy — změna režimu/limitu, formát požadavku nezachycen), `api/charging/equ/detail`, `api/charging/equ/detailChart/export`, `api/user/info`, `api/user/changePwd`, `api/com/getWebVer`. Pokud potřebujete zápisové ovládání (start/stop, změna `max_cur`, přepnutí `mode`), začněte zachycením reálné relace prohlížeče při provedení dané akce (DevTools → Network, nebo stejný postup s HAR záznamem jako zde), místo hádání formátu požadavku.

## 3. Integrace Home Assistant

Kód je v [`custom_components/renac_wallbox/`](custom_components/renac_wallbox/):

| Soubor | Odpovědnost |
|---|---|
| [`api.py`](custom_components/renac_wallbox/api.py) | `RenacApiClient` — přihlášení, podepisování požadavků, všechna ověřená volání endpointů |
| [`const.py`](custom_components/renac_wallbox/const.py) | Doména, základní URL, salt pro podpis, kódy odpovědí, ověřené výčty |
| [`coordinator.py`](custom_components/renac_wallbox/coordinator.py) | `DataUpdateCoordinator` dotazující `api/charging/index` (2.4) každých 30 s (nastavitelné) |
| [`config_flow.py`](custom_components/renac_wallbox/config_flow.py) | UI nastavení: základní URL + e-mail + heslo → výběr stanice → výběr zařízení |
| [`sensor.py`](custom_components/renac_wallbox/sensor.py) | Jedna entita na ověřené pole (výkon, napětí, proud, energie, náklady, stav, režim, fáze, limity) |
| [`binary_sensor.py`](custom_components/renac_wallbox/binary_sensor.py) | Binární senzor `fault` (`state2 == 5`) |
| [`manifest.json`](custom_components/renac_wallbox/manifest.json), [`strings.json`](custom_components/renac_wallbox/strings.json), [`translations/`](custom_components/renac_wallbox/translations/) | Metadata HA + CZ/EN překlady config flow a entit |

Jeden config entry = jedno zařízení wallbox (`inv_sn`). Pro účty s více wallboxy přidejte integraci vícekrát, jednou na zařízení (config flow vás provede výběrem stanice a zařízení, pokud je jich víc).

### 3.1 Instalace

Doporučená cesta je přes **HACS**, podrobně popsaná krok za krokem v §0 výše. Funguje i ruční instalace bez HACS:
1. Zkopírujte `custom_components/renac_wallbox/` do adresáře `config/custom_components/` vašeho Home Assistant.
2. Restartujte Home Assistant.
3. Nastavení → Zařízení a služby → Přidat integraci → hledejte "RENAC Wallbox".

### 3.2 Config flow

1. Zadejte základní URL API (výchozí je ověřený evropský endpoint), e-mail a heslo — stejné přihlašovací údaje jako na `seceu.renacpower.com`.
2. Pokud má účet více wallbox stanic, vyberte jednu.
3. Pokud má daná stanice více zařízení, vyberte sériové číslo.
4. Entity se vytvoří pod jedním zařízením na `inv_sn`.

Výchozí interval dotazování je 30 s, lze změnit později přes **Konfigurovat** u integrace (options flow), v rozsahu 10–3600 s.

### 3.3 Co dostanete

Senzory: výkon (W), napětí (V), proud (A), celková energie (kWh, `total_increasing`), energie relace (kWh), celkové náklady, náklady relace, doba trvání relace, stav (`idle`/`plugged_in`/`charging`/`fault`), režim (`fast`/`pv`/`off_peak`), fáze (`single_phase`/`three_phase`), limit max. proudu, limit max. výkonu, PV práh minimálního solárního výkonu (diagnostický). Plus binární senzor `problem` pro stav poruchy.

Zatím neimplementováno, ponecháno jako budoucí práce: senzor historie relací z bodu 2.7, diagnostika po fázích z bodu 2.8, a jakékoli zápisové/ovládací entity proti `api/charging/set` (2.9), protože formát jeho požadavku nebyl ověřen na reálném účtu.

### 3.4 Známé mezery / co by měl implementující agent ověřit dále

1. **Jiné regiony než Evropa** — ověřte vzor základní URL pro Asii/Jižní Ameriku (nebo jiný region) na reálném účtu, než to nasadíte pro uživatele mimo EU; v současnosti je nabídnut jen odhadnutý vzor hostname.
2. **Volání pro vyhledání zařízení (2.5)** — nezachyceno naživo; pokud nevrací očekávaný tvar `list[].INV_SN`, bude potřeba upravit krok výběru zařízení v config flow.
3. **`api/charging/set`** — zachyťte reálnou akci "změna režimu nabíjení" nebo "změna limitu proudu" z webového portálu (karta Network v DevTools prohlížeče, nebo export HAR jako u tohoto dokumentu), než přidáte ovládací entity typu number/select.
4. **Životnost tokenu / frekvence opětovného přihlášení** — integrace se znovu přihlašuje reaktivně (při `msg == "1000"`), ale skutečná platnost tokenu nebyla změřena; zvažte, zda má smysl přidat proaktivní opětovné přihlášení na časovač, až to bude v praxi pozorováno.
5. **Pole `state` vs. `unit`** — zatím nevysvětlená; pokud zjistíte jejich význam (např. vyvoláním poruchy nebo změnou měny), zapracujte to do `const.py`.

### 3.5 Bezpečnostní poznámky

* Přihlašovací endpoint RENAC přijímá **heslo v čistém textu přes HTTPS** — na klientovi není žádné hashování, které by bylo třeba zachovat. Ukládejte přihlašovací údaje stejně, jako Home Assistant ukládá údaje jakékoli jiné integrace (v config entry, šifrováno na disku, pokud to má HA nastaveno).
* Salt pro podepisování (`SIGN_SALT` v `const.py`) je statický řetězec zabudovaný přímo do veřejného webového klienta RENAC — považovat ho za tajemství by nemělo smysl (posílá se při každém načtení stránky), ale při zveřejnění tohoto projektu jej neprezentujte jako tajemství vašeho vlastního kódu.
* Tato integrace ve stávající podobě provádí pouze **čtecí** operace proti zdokumentovaným, pozorovaným endpointům. Nikdy nezapisuje do `api/charging/set` ani podobných řídicích endpointů.

### 3.6 Testování (bez nutnosti reálných přihlašovacích údajů)

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
# API Home Assistant — přesnou posloupnost curl příkazů najdete v historii
# commitů, nebo to projeďte přes UI na http://localhost:18123 s libovolným
# e-mailem/heslem (mock přijme cokoli) a základní URL
# http://mock-renac-api:8084.
docker compose -f docker-compose.test.yml down
```
Očekávejte, že se pod `/api/states` objeví `sensor.wallbox_..._power`, `..._voltage`, `..._state` (`idle`), `..._charge_mode` (`pv`) atd., odpovídající hodnotám polí zdokumentovaným v §2.4.
