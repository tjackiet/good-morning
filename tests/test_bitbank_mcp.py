"""good_morning.collector.bitbank_mcp のテスト（MCP の結果の取り出しと失敗の扱い）"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from good_morning.collector import bitbank_mcp
from good_morning.collector.bitbank_mcp import (
    BitbankMCPError,
    BitbankSnapshot,
    snapshot_calls,
    structured_from_result,
)

# autouse のフィクスチャが差し替える前の本物（import 時点で取っておく）
REAL_FETCH_SNAPSHOT = bitbank_mcp.fetch_snapshot


def _result(structured=None, is_error=False, text=""):
    return SimpleNamespace(
        structured_content=structured,
        is_error=is_error,
        content=[SimpleNamespace(text=text)],
    )


def test_snapshot_calls_cover_three_timeframes_and_tickers():
    calls = snapshot_calls("btc_jpy")

    assert [(c.key, c.tool) for c in calls] == [
        ("indicators_1day", "analyze_indicators"),
        ("indicators_1week", "analyze_indicators"),
        ("indicators_1month", "analyze_indicators"),
        ("tickers_jpy", "get_tickers_jpy"),
    ]
    assert calls[0].arguments == {"pair": "btc_jpy", "type": "1day", "limit": 300}


def test_structured_from_result_uses_structured_content_only():
    structured = {"ok": True, "data": {"x": 1}}

    assert structured_from_result("k", _result(structured, text="文章は使わない")) == structured


@pytest.mark.parametrize(
    "result,match",
    [
        (_result(None), "structuredContent がありません"),
        (_result({"ok": False, "summary": "bad pair"}), "ok=false"),
        (_result({"ok": True}, is_error=True, text="boom"), "エラーを返しました"),
    ],
)
def test_structured_from_result_rejects_bad_results(result, match):
    with pytest.raises(BitbankMCPError, match=match):
        structured_from_result("k", result)


def test_snapshot_get_raises_recorded_error():
    snapshot = BitbankSnapshot(results={"a": {"ok": True}}, errors={"b": "b: Timeout"})

    assert snapshot.get("a") == {"ok": True}
    with pytest.raises(BitbankMCPError, match="Timeout"):
        snapshot.get("b")
    with pytest.raises(BitbankMCPError):
        snapshot.get("c")


def test_one_failing_tool_does_not_stop_the_others(monkeypatch):
    """1つのツールが失敗しても、残りのツールは呼んで結果を残す"""

    class FakeSession:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def initialize(self):
            pass

        async def call_tool(self, tool, arguments):
            if arguments.get("type") == "1week":
                raise TimeoutError("slow")
            return _result({"ok": True, "tool": tool})

    @asynccontextmanager
    async def fake_stdio_client(params):
        yield ("read", "write")

    monkeypatch.setattr(bitbank_mcp, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(bitbank_mcp, "ClientSession", FakeSession)

    snapshot = REAL_FETCH_SNAPSHOT(snapshot_calls())

    assert set(snapshot.results) == {"indicators_1day", "indicators_1month", "tickers_jpy"}
    assert "TimeoutError" in snapshot.errors["indicators_1week"]


def test_connection_failure_is_wrapped(monkeypatch):
    @asynccontextmanager
    async def broken_stdio_client(params):
        raise FileNotFoundError("npx not found")
        yield  # pragma: no cover

    monkeypatch.setattr(bitbank_mcp, "stdio_client", broken_stdio_client)

    with pytest.raises(BitbankMCPError, match="接続できませんでした"):
        REAL_FETCH_SNAPSHOT(snapshot_calls())


def test_server_does_not_receive_api_keys(monkeypatch):
    """公開データだけを使うので、子プロセスに API キーを渡さない"""
    monkeypatch.setenv("BITBANK_API_KEY", "should-not-leak")

    params = bitbank_mcp.server_parameters()

    assert params.env is None or "BITBANK_API_KEY" not in params.env
    assert params.args == ["-y", bitbank_mcp.SERVER_PACKAGE]
