"""Unit tests for RenacApiClient, replaying real (sanitized) response
shapes captured from a live seceu.renacpower.com session — see
tests/fixtures/renac_api/. No network access, no real credentials.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from aiohttp import web

from _load_component import load_component

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "renac_api"

const = load_component("const")
api_module = load_component("api")
RenacApiClient = api_module.RenacApiClient
CHARGE_MODES = const.CHARGE_MODES
CHARGE_STATES = const.CHARGE_STATES
SIGN_SALT = const.SIGN_SALT


def load_fixture(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


class FakeRenacServer:
    """Minimal aiohttp app replaying captured fixture responses.

    Also verifies the Token/timestamp/sign headers on every authenticated
    call, so these tests exercise the real signing implementation end to
    end, not just JSON parsing.
    """

    TOKEN = "test-mock-token"

    def __init__(self) -> None:
        self.received_paths: list[str] = []
        self.app = web.Application()
        self.app.router.add_post("/api/user/login", self.login)
        self.app.router.add_post("/api/station/list", self.station_list)
        self.app.router.add_post("/api/charging/index", self.charging_index)
        self.app.router.add_post("/bg/equList", self.equ_list)
        self.app.router.add_post("/api/station/equipStat", self.equip_stat)

    async def _check_signature(self, request: web.Request) -> None:
        token = request.headers.get("Token")
        timestamp = request.headers.get("timestamp")
        sign = request.headers.get("sign")
        assert token == self.TOKEN
        expected = hashlib.md5(f"{token}{timestamp}{SIGN_SALT}".encode()).hexdigest()
        assert sign == expected, "client-computed sign does not match server expectation"

    async def login(self, request: web.Request) -> web.Response:
        self.received_paths.append(request.path)
        body = await request.json()
        assert set(body.keys()) == {"login_name", "pwd"}
        return web.json_response(load_fixture("login.json"))

    async def station_list(self, request: web.Request) -> web.Response:
        self.received_paths.append(request.path)
        await self._check_signature(request)
        return web.json_response(load_fixture("station_list.json"))

    async def charging_index(self, request: web.Request) -> web.Response:
        self.received_paths.append(request.path)
        await self._check_signature(request)
        return web.json_response(load_fixture("charging_index.json"))

    async def equ_list(self, request: web.Request) -> web.Response:
        self.received_paths.append(request.path)
        await self._check_signature(request)
        return web.json_response(
            {"code": 1, "msg": "0000", "data": {"total": 1, "list": [{"INV_SN": "ABC0123456DEF789"}]}}
        )

    async def equip_stat(self, request: web.Request) -> web.Response:
        self.received_paths.append(request.path)
        await self._check_signature(request)
        return web.json_response(load_fixture("equip_stat.json"))


@pytest.fixture
async def server(aiohttp_client):
    fake = FakeRenacServer()
    client = await aiohttp_client(fake.app)
    client.fake = fake
    return client


async def test_login_stores_token_and_user_id(server):
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    user_id = await api.async_login()
    assert user_id == 100001
    assert api.token == "test-mock-token"


async def test_get_wallbox_status_parses_real_shape(server):
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    await api.async_login()
    status = await api.async_get_wallbox_status("ABC0123456DEF789")

    # Field-for-field against the real captured session (README §2.4).
    assert status["charger_power"] == 0
    assert status["charger_vol"] == 236.5
    assert status["charger_total_energy"] == 3244.1
    assert status["max_cur"] == 7
    assert status["pv"]["min_solar_power"] == 8000

    assert CHARGE_STATES[status["state2"]] == "idle"
    assert CHARGE_MODES[status["mode"]] == "pv"


async def test_get_stations_filters_wallbox_type(server):
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    user_id = await api.async_login()
    stations = await api.async_get_wallbox_stations(user_id)
    assert len(stations) == 1
    assert stations[0]["station_type"] == 8
    assert stations[0]["station_name"] == "Wallbox 000000"


async def test_get_equip_stat(server):
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    user_id = await api.async_login()
    stat = await api.async_get_equip_stat(user_id, 200001)
    assert stat["total_online_equip"] == 1
    assert stat["total_alarm_equip"] == 0


async def test_get_station_devices_uses_bg_equlist(server):
    """Regression test: this used to incorrectly call api/charging/index
    with a {station_id, user_id, ...} body, which the real API accepts
    but answers with `data: null` -- confirmed against a live account.
    The correct endpoint is bg/equList."""
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    user_id = await api.async_login()
    devices = await api.async_get_station_devices(user_id, 200001)
    assert devices == [{"INV_SN": "ABC0123456DEF789"}]
    assert "/bg/equList" in server.fake.received_paths


async def test_requests_are_actually_signed(server):
    """Confirms the client never calls an authenticated endpoint without a
    valid Token/timestamp/sign triple — the mock server asserts this on
    every call, so simply completing the round trip is the test."""
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    await api.async_login()
    await api.async_get_wallbox_status("ABC0123456DEF789")
    assert "/api/charging/index" in server.fake.received_paths
