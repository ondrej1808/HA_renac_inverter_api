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
    return web.json_response(load("charging_index.json"))


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
    app.router.add_post("/bg/equList", equ_list)
    app.router.add_post("/api/station/equipStat", equip_stat)
    app.router.add_post("/api/charging/equ/charging_record", charging_record)
    app.router.add_post("/api/charging/equ/detailChart", detail_chart)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8084)
