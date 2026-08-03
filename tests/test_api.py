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
        self.app.router.add_post("/api/charging/basic", self.charging_basic)
        self.app.router.add_post("/api/charging/fast", self.charging_fast)
        self.app.router.add_post("/api/charging/pv", self.charging_pv)
        self.app.router.add_post("/api/charging/off-peak", self.charging_off_peak)
        self.app.router.add_post("/api/charging/set", self.charging_set)
        self.app.router.add_post("/bg/equList", self.equ_list)
        self.app.router.add_post("/api/station/equipStat", self.equip_stat)
        self.charging_index_state = load_fixture("charging_index.json")["data"]
        self.charging_basic_state = load_fixture("charging_basic.json")["data"]
        self.charging_fast_state = load_fixture("charging_fast.json")["data"]
        self.charging_pv_state = load_fixture("charging_pv.json")["data"]
        self.charging_off_peak_state = load_fixture("charging_off_peak.json")["data"]
        self.set_calls: list[dict] = []
        self._set_type_state = {
            1: self.charging_basic_state,
            2: self.charging_basic_state,
            3: self.charging_index_state,
            4: self.charging_fast_state,
            5: self.charging_pv_state,
            6: self.charging_off_peak_state,
        }

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
        return web.json_response({"code": 1, "msg": "0000", "data": self.charging_index_state})

    async def charging_basic(self, request: web.Request) -> web.Response:
        self.received_paths.append(request.path)
        await self._check_signature(request)
        return web.json_response({"code": 1, "msg": "0000", "data": self.charging_basic_state})

    async def charging_fast(self, request: web.Request) -> web.Response:
        self.received_paths.append(request.path)
        await self._check_signature(request)
        return web.json_response({"code": 1, "msg": "0000", "data": self.charging_fast_state})

    async def charging_pv(self, request: web.Request) -> web.Response:
        self.received_paths.append(request.path)
        await self._check_signature(request)
        return web.json_response({"code": 1, "msg": "0000", "data": self.charging_pv_state})

    async def charging_off_peak(self, request: web.Request) -> web.Response:
        self.received_paths.append(request.path)
        await self._check_signature(request)
        return web.json_response({"code": 1, "msg": "0000", "data": self.charging_off_peak_state})

    async def charging_set(self, request: web.Request) -> web.Response:
        self.received_paths.append(request.path)
        await self._check_signature(request)
        body = await request.json()
        self.set_calls.append(body)
        state = self._set_type_state[body["type"]]
        for field, value in zip(body["ids"].split(","), body["params"].split(",")):
            try:
                value = float(value)
                if value.is_integer():
                    value = int(value)
            except ValueError:
                pass
            state[field] = value
            if field == "max_output_cur":
                self.charging_index_state["max_cur"] = value
            if field == "charger_mode":
                self.charging_index_state["mode"] = value
        return web.json_response({"code": 1, "msg": "0000", "data": None})

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

    # Field-for-field against the real captured session (docs/API.md §2.4).
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


async def test_get_charging_basic(server):
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    await api.async_login()
    basic = await api.async_get_charging_basic("ABC0123456DEF789")
    assert basic["max_output_cur"] == 7


async def test_set_max_current_sends_expected_payload(server):
    """Confirms the exact api/charging/set request shape reverse
    engineered from the settings form's setMode(2) method: type=2,
    ids/params as single-item comma-joined lists for a one-field write."""
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    await api.async_login()
    await api.async_set_max_current("ABC0123456DEF789", 16)

    assert len(server.fake.set_calls) == 1
    call = server.fake.set_calls[0]
    assert call == {
        "equ_sn": "ABC0123456DEF789",
        "type": 2,
        "ids": "max_output_cur",
        "params": "16",
    }

    # And the mock reflects it back on subsequent reads, same as the
    # real API would after a successful write.
    status = await api.async_get_wallbox_status("ABC0123456DEF789")
    assert status["max_cur"] == 16


async def test_get_charging_fast_pv_off_peak(server):
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    await api.async_login()

    fast = await api.async_get_charging_fast("ABC0123456DEF789")
    assert fast["mode"] == 0
    assert fast["time_begintime"] == "22:00"

    pv = await api.async_get_charging_pv("ABC0123456DEF789")
    assert pv["min_solar_power"] == 8000

    off_peak = await api.async_get_charging_off_peak("ABC0123456DEF789")
    assert off_peak["balance_power"] == 0


async def test_set_charger_mode_sends_expected_payload(server):
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    await api.async_login()
    await api.async_set_charger_mode("ABC0123456DEF789", 1)

    assert server.fake.set_calls[-1] == {
        "equ_sn": "ABC0123456DEF789",
        "type": 3,
        "ids": "charger_mode",
        "params": "1",
    }
    status = await api.async_get_wallbox_status("ABC0123456DEF789")
    assert status["mode"] == 1


async def test_set_pv_settings_sends_expected_payload(server):
    """type=5, multi-field write in one call (import_grid + min_solar_power)."""
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    await api.async_login()
    await api.async_set_charging(
        "ABC0123456DEF789", 5, {"import_grid": 1, "min_solar_power": 6000}
    )

    assert server.fake.set_calls[-1] == {
        "equ_sn": "ABC0123456DEF789",
        "type": 5,
        "ids": "import_grid,min_solar_power",
        "params": "1,6000",
    }
    pv = await api.async_get_charging_pv("ABC0123456DEF789")
    assert pv["min_solar_power"] == 6000


async def test_set_off_peak_load_balance_shares_type_6(server):
    """type=6 is shared between off-peak schedule and load-balance
    fields (README §2.10) -- confirms both write into the same group."""
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    await api.async_login()
    await api.async_set_charging("ABC0123456DEF789", 6, {"balance": 1, "balance_power": 5000})

    off_peak = await api.async_get_charging_off_peak("ABC0123456DEF789")
    assert off_peak["balance"] == 1
    assert off_peak["balance_power"] == 5000


async def test_requests_are_actually_signed(server):
    """Confirms the client never calls an authenticated endpoint without a
    valid Token/timestamp/sign triple — the mock server asserts this on
    every call, so simply completing the round trip is the test."""
    api = RenacApiClient(server.session, str(server.make_url("")), "test@example.com", "x")
    await api.async_login()
    await api.async_get_wallbox_status("ABC0123456DEF789")
    assert "/api/charging/index" in server.fake.received_paths
