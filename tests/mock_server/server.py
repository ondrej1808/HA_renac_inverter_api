"""Standalone mock RENAC cloud API used for local/Docker end-to-end testing
of the renac_wallbox Home Assistant integration.

Replays the same sanitized, real-shaped fixtures used by the unit tests
(tests/fixtures/renac_api/) and enforces the real Token/timestamp/sign
signing scheme, so a config-flow run against this server exercises the
exact same code path as talking to the real seceu.renacpower.com API --
minus any real credentials, tokens, or network egress. Accepts any
login_name/pwd (this is a test double, not an auth server).
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from aiohttp import web

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger("mock_renac_api")

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SIGN_SALT = "9P@3kF7sD2&zX5cV8bNm1qR4tY6uI0o"
TOKEN = "test-mock-token"


def load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


# Mutable in-memory state so a charging/set write is actually reflected
# by subsequent reads -- lets the Docker e2e test verify the full
# entity round trip, not just that the write call returns code=1.
_charging_index_state = load("charging_index.json")["data"]
_charging_basic_state = load("charging_basic.json")["data"]
_charging_fast_state = load("charging_fast.json")["data"]
_charging_pv_state = load("charging_pv.json")["data"]
_charging_off_peak_state = load("charging_off_peak.json")["data"]

# api/charging/set `type` -> which state dict its `ids` write into.
_SET_TYPE_STATE = {
    1: _charging_basic_state,  # rfid
    2: _charging_basic_state,
    3: _charging_index_state,  # charger_mode (mirrors into `mode`, see below)
    4: _charging_fast_state,
    5: _charging_pv_state,
    6: _charging_off_peak_state,
}


def check_signature(request: web.Request) -> web.Response | None:
    token = request.headers.get("Token")
    timestamp = request.headers.get("timestamp")
    sign = request.headers.get("sign")
    if token != TOKEN or not timestamp or not sign:
        return web.json_response({"code": 400, "msg": "1000", "data": None}, status=200)
    expected = hashlib.md5(f"{token}{timestamp}{SIGN_SALT}".encode()).hexdigest()
    if sign != expected:
        _LOGGER.warning("Bad signature: got %s expected %s", sign, expected)
        return web.json_response({"code": 400, "msg": "1000", "data": None}, status=200)
    return None


async def login(request: web.Request) -> web.Response:
    body = await request.json()
    _LOGGER.info("POST /api/user/login login_name=%s", body.get("login_name"))
    return web.json_response(load("login.json"))


async def station_list(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    _LOGGER.info("POST /api/station/list")
    return web.json_response(load("station_list.json"))


async def charging_index(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    body = await request.json()
    _LOGGER.info("POST /api/charging/index body=%s", body)
    return web.json_response({"code": 1, "msg": "0000", "data": _charging_index_state})


async def charging_basic(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    _LOGGER.info("POST /api/charging/basic")
    return web.json_response({"code": 1, "msg": "0000", "data": _charging_basic_state})


async def charging_fast(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    _LOGGER.info("POST /api/charging/fast")
    return web.json_response({"code": 1, "msg": "0000", "data": _charging_fast_state})


async def charging_pv(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    _LOGGER.info("POST /api/charging/pv")
    return web.json_response({"code": 1, "msg": "0000", "data": _charging_pv_state})


async def charging_off_peak(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    _LOGGER.info("POST /api/charging/off-peak")
    return web.json_response({"code": 1, "msg": "0000", "data": _charging_off_peak_state})


async def charging_set(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    body = await request.json()
    _LOGGER.info("POST /api/charging/set body=%s", body)
    set_type = body.get("type")
    state = _SET_TYPE_STATE.get(set_type)
    if state is None:
        return web.json_response({"code": 400, "msg": "9999", "data": None})

    ids = (body.get("ids") or "").split(",")
    raw_params = body.get("params")
    # charger_cmd is sent as a raw JSON int, not a comma-joined string
    # like every other charging/set write -- confirmed live (§2.10).
    params = raw_params.split(",") if isinstance(raw_params, str) else [raw_params]
    for field, value in zip(ids, params):
        if not field:
            continue
        try:
            value = float(value)
            if value.is_integer():
                value = int(value)
        except (ValueError, TypeError):
            pass
        state[field] = value
        if field == "max_output_cur":
            _charging_index_state["max_cur"] = value
        if field == "charger_mode":
            _charging_index_state["mode"] = value
        if field == "charger_cmd":
            _charging_index_state["state2"] = 3 if value == 1 else 4
    return web.json_response({"code": 1, "msg": "0000", "data": None})


async def equ_list(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    _LOGGER.info("POST /bg/equList")
    return web.json_response(
        {"code": 1, "msg": "0000", "data": {"total": 1, "list": [{"INV_SN": "ABC0123456DEF789"}]}}
    )


async def equip_stat(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    _LOGGER.info("POST /api/station/equipStat")
    return web.json_response(load("equip_stat.json"))


async def charging_record(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    _LOGGER.info("POST /api/charging/equ/charging_record")
    return web.json_response(load("charging_record.json"))


async def detail_chart(request: web.Request) -> web.Response:
    if (err := check_signature(request)) is not None:
        return err
    _LOGGER.info("POST /api/charging/equ/detailChart")
    return web.json_response(load("detail_chart.json"))


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/user/login", login)
    app.router.add_post("/api/station/list", station_list)
    app.router.add_post("/api/charging/index", charging_index)
    app.router.add_post("/api/charging/basic", charging_basic)
    app.router.add_post("/api/charging/fast", charging_fast)
    app.router.add_post("/api/charging/pv", charging_pv)
    app.router.add_post("/api/charging/off-peak", charging_off_peak)
    app.router.add_post("/api/charging/set", charging_set)
    app.router.add_post("/bg/equList", equ_list)
    app.router.add_post("/api/station/equipStat", equip_stat)
    app.router.add_post("/api/charging/equ/charging_record", charging_record)
    app.router.add_post("/api/charging/equ/detailChart", detail_chart)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8084)
