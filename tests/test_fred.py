"""good_morning.collector.fred のテスト（ページ送り・エラー時に API キーを漏らさない）"""

from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from conftest import FRED_SYNTHETIC_FIXTURE, load_fixture_json

from good_morning.collector import fred
from good_morning.collector.fred import FredError, fetch_release_dates, get_api_key

API_KEY = "abcdef0123456789secret"


def _response(status: int, payload):
    def _json():
        if isinstance(payload, Exception):
            raise payload
        return payload

    return SimpleNamespace(status_code=status, json=_json)


def test_fetch_release_dates_filters_by_window(monkeypatch):
    payload = load_fixture_json(FRED_SYNTHETIC_FIXTURE)
    seen_params = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen_params.append(params)
        assert headers["User-Agent"]
        return _response(200, payload)

    monkeypatch.setattr(fred.httpx, "get", fake_get)

    rows = fetch_release_dates(date(2026, 11, 17), date(2026, 12, 17), api_key=API_KEY)

    assert [r.date for r in rows][-1] == date(2026, 12, 11)  # 2027-01-13 は期間外
    assert seen_params[0]["include_release_dates_with_no_data"] == "true"
    assert seen_params[0]["sort_order"] == "asc"
    assert len(seen_params) == 1  # count が1ページに収まっている


def test_fetch_release_dates_pages_until_window_end(monkeypatch):
    def page(offset):
        day = 1 + offset // fred.PAGE_LIMIT  # 1ページ目は 12/1、2ページ目は 12/2 ...
        rows = [
            {"release_id": 1, "release_name": "X", "date": f"2026-12-{day:02d}"}
        ] * fred.PAGE_LIMIT
        return {"count": fred.PAGE_LIMIT * 5, "release_dates": rows}

    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params["offset"])
        return _response(200, page(params["offset"]))

    monkeypatch.setattr(fred.httpx, "get", fake_get)

    rows = fetch_release_dates(date(2026, 12, 1), date(2026, 12, 2), api_key=API_KEY)

    # 3ページ目（12/3）で期間を過ぎたので止まる
    assert calls == [0, 1000, 2000]
    assert len(rows) == 2 * fred.PAGE_LIMIT


def test_http_error_message_hides_api_key(monkeypatch):
    payload = {"error_code": 400, "error_message": f"Bad Request. api_key {API_KEY} is not registered"}
    monkeypatch.setattr(fred.httpx, "get", lambda *a, **k: _response(400, payload))

    with pytest.raises(FredError) as excinfo:
        fetch_release_dates(date(2026, 11, 17), date(2026, 12, 17), api_key=API_KEY)

    assert "HTTP 400" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


def test_connection_error_hides_url_and_keeps_cause_types(monkeypatch):
    """httpx の例外メッセージは URL（＝キー）を含むので使わない。原因の型名はたどって残す"""

    def fake_get(url, params=None, **kwargs):
        try:
            raise OSError("certificate verify failed")
        except OSError as cause:
            raise httpx.ConnectError(f"failed: {url}?api_key={params['api_key']}") from cause

    monkeypatch.setattr(fred.httpx, "get", fake_get)

    with pytest.raises(FredError) as excinfo:
        fetch_release_dates(date(2026, 11, 17), date(2026, 12, 17), api_key=API_KEY)

    message = str(excinfo.value)
    assert API_KEY not in message and "api.stlouisfed.org" not in message
    assert "ConnectError ← OSError" in message
    # トレースバックにも元の例外（URL 入り）を残さない
    assert excinfo.value.__suppress_context__ is True


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    with pytest.raises(FredError, match="FRED_API_KEY"):
        get_api_key()
