"""Constants for the RENAC Wallbox integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "renac_wallbox"

# Confirmed working base URL for the "Europe" region (captured from
# window.baseUrl.path in the seceu.renacpower.com web app bundle).
# Other regions almost certainly follow the same pattern
# (<region>.renacpower.com:8084) but have NOT been verified against a
# real account. Expose the base URL as a user-editable config option so
# users outside Europe can override it without a code change.
DEFAULT_BASE_URL = "https://europe.renacpower.com:8084"

KNOWN_BASE_URLS = {
    "europe": "https://europe.renacpower.com:8084",
    # Unverified — inferred only from the "region_asia" / "region_south_america"
    # i18n keys found in the web bundle. Confirm before relying on these.
    "asia": "https://asia.renacpower.com:8084",
    "south_america": "https://southamerica.renacpower.com:8084",
    "custom": "",
}

# Hardcoded signing salt lifted verbatim from the minified web app
# (chunk containing the axios request interceptor). It is concatenated
# with the token and the unix timestamp, then MD5-hashed, to produce the
# `sign` header required by every authenticated endpoint. This is a
# static secret baked into the client-side JS, not a per-user secret.
SIGN_SALT = "9P@3kF7sD2&zX5cV8bNm1qR4tY6uI0o"

# Response envelope
CODE_SUCCESS = 1
CODE_ERROR = 400
MSG_TOKEN_INVALID = "1000"  # -> must re-login
MSG_CLOCK_SKEW = "1008"     # -> data field holds the minute offset

# station_type value that identifies an AC wallbox / charging pile station
# (confirmed: station_type == 8 in api/station/list, and the SPA routes
# station_type 8 to the "pileStationDetail" / charging views).
STATION_TYPE_WALLBOX = 8

# api/charging/index -> data.mode (confirmed via i18n modeArr ordering)
CHARGE_MODES = {
    0: "fast",
    1: "pv",
    2: "off_peak",
}

# api/charging/set type=3, ids="charger_cmd" -- CONFIRMED live via a real
# HAR capture of the "turn on"/"turn off charging" buttons (2026-08-03).
# The only write value in this integration verified against a real
# network request rather than derived from decompiled JS.
CHARGER_CMD_START = 1
CHARGER_CMD_STOP = 2

# state2 values that mean "actively delivering current" (see CHARGE_STATES
# below) -- used by switch.py's charging on/off entity to report is_on.
CHARGING_ACTIVE_STATES = {3, 6}

# api/charging/index -> data.state2 (confirmed via i18n pileState ordering:
# pile_state0=Idle(空闲), pile_state124=Plugged in, not charging(插枪未充电),
# pile_state36=Charging(充电中), pile_state5=Fault(故障))
CHARGE_STATES = {
    0: "idle",
    1: "plugged_in",
    2: "plugged_in",
    3: "charging",
    4: "plugged_in",
    5: "fault",
    6: "charging",
}

# api/charging/index -> data.phase (confirmed via i18n phaseArr ordering)
CHARGE_PHASES = {
    0: "single_phase",
    1: "three_phase",
}

# --- The following enums are derived from the SetPile settings-form
# component's own data() defaults (decompiled JS), not live-captured.
# See docs/API.md §2.10 for the full writeup and confidence level.

# api/charging/basic -> data.charing_mode (SPA's own spelling; chargeArr
# i18n ordering: ["APP", rfid_card, plug_char])
BASIC_CHARGE_AUTH_MODES = {
    0: "app",
    1: "rfid_card",
    2: "plug_and_charge",
}

# api/charging/basic -> data.external_cur_sampling (samplingArr i18n
# ordering: none, in_ct_con, smart_ele_meter, single_h_hybrid, three_h_hybrid)
EXTERNAL_CUR_SAMPLING_MODES = {
    0: "none",
    1: "ct_connected",
    2: "smart_meter",
    3: "single_phase_hybrid",
    4: "three_phase_hybrid",
}

# api/charging/pv -> data.boost (pvPlanArr i18n ordering, options bound
# with `value: index + 1`; 0 = off is implied by `pvParam.import_grid ||
# (pvParam.boost = 0)` in the component's readPv() handler)
PV_BOOST_MODES = {
    0: "off",
    1: "manual",
    2: "intelligent",
}

# api/charging/fast -> data.mode (fastPlanArr i18n ordering: time,
# generation [energy], char_cost [cost])
FAST_CHARGE_PLANS = {
    0: "time",
    1: "energy",
    2: "cost",
}

CONF_BASE_URL = "base_url"
CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"
CONF_INV_SN = "inv_sn"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=10)
# Settings (basic/fast/pv/off-peak) change far less often than telemetry
# and are unconfirmed-write endpoints -- poll them gently.
SETTINGS_SCAN_INTERVAL = timedelta(seconds=300)

PLATFORMS = ["sensor", "binary_sensor", "number", "select", "switch", "time"]
