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

CONF_BASE_URL = "base_url"
CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"
CONF_INV_SN = "inv_sn"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)

PLATFORMS = ["sensor", "binary_sensor"]
