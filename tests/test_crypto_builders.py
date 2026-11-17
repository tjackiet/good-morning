"""BTCの詳細・暗号資産ウォッチリスト・マーケット一覧の BTC/JPY 行（実データの fixtures で確認）"""

import copy
import logging
from datetime import datetime

import pytest
from conftest import BITBANK_FIXTURE, YF_PRE_OPEN_FIXTURE, load_fixture_json

from good_morning.context import RunContext
from good_morning.crypto.builders import build_btc, build_crypto_watchlist
from good_morning.crypto.tickers import format_price_text
from good_morning.markets.builders import build_markets
from good_morning.paths import CONFIG_DIR
from good_morning.reporter.markdown import STATUS_FAILED, STATUS_OK
from good_morning.sections import SECTION_SPECS, build_sections
from good_morning.timeutil import JST
from good_morning.watchlist import load_watchlist

NOW = datetime(2026, 11, 17, 23, 9, tzinfo=JST)
BITBANK_LINE = (
    "BTC・暗号資産: bitbank の取得時点の値（2026-11-17 23:09 JST）。日足・週足・月足は形成中の足を含む"
)


@pytest.fixture
def ctx():
    return RunContext(now=NOW, watchlist=load_watchlist(CONFIG_DIR))


def _table(body: str, first_header: str) -> dict[str, list[str]]:
    """first_header で始まる Markdown の表を {1列目: [残りの列]} にする"""
    rows, inside = {}, False
    for line in body.splitlines():
        if line.startswith(f"| {first_header}"):
            inside = True
            continue
        if inside:
            if not line.startswith("|"):
                break
            if line.startswith("|---"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows[cells[0]] = cells[1:]
    return rows


def test_btc_section_from_real_snapshot(fake_bitbank, ctx):
    fake_bitbank(BITBANK_FIXTURE)

    content = build_btc(ctx)
    table = _table(content.body, "|")  # 見出し行は「| | 日足 | 週足 | 月足 |」

    assert "**BTC/JPY 10,344,652円**（24時間 +1.28%）" in content.body
    assert table["一目：雲との位置"] == ["🔴 雲の下", "🔴 雲の下", "🟢 雲の上"]
    assert table["一目：三役"] == ["🔴 三役逆転", "⚪ なし（強気 1/3）", "⚪ なし（強気 2/3）"]
    assert table["移動平均の並び（25/75/200本）"][2] == "🟢 上昇の並び（25 > 75）（200本は算出不可）"
    assert table["ボリンジャーバンドのσ位置"] == ["-1.76σ", "-1.13σ", "-1.19σ"]
    assert table["RSI(14)"] == ["🔴 25.6（売られすぎ）", "🔴 39.0（弱め）", "⚪ 45.5（中立）"]
    assert table["判定"] == ["**弱気**（-4）", "**弱気**（-3）", "**中立**（+1）"]
    assert "| 11/11（水） |" in content.body and "11/17（火）※" in content.body
    assert "形成中" in content.body
    assert content.basis == [BITBANK_LINE]
    assert set(ctx.data["btc_assessments"]) == {"1day", "1week", "1month"}


def test_btc_section_marks_failed_timeframe(fake_bitbank, ctx):
    data = load_fixture_json(BITBANK_FIXTURE)
    del data["results"]["indicators_1week"]
    data["errors"] = {"indicators_1week": "indicators_1week: TimeoutError"}
    fake_bitbank(data)

    table = _table(build_btc(ctx).body, "|")

    assert table["判定"] == ["**弱気**（-4）", "取得失敗", "**中立**（+1）"]


def test_crypto_watchlist_from_real_snapshot(fake_bitbank, ctx):
    fake_bitbank(BITBANK_FIXTURE)

    content = build_crypto_watchlist(ctx)
    rows = _table(content.body, "銘柄")

    assert list(rows) == [
        "BTC/JPY（基準）", "ETH/JPY", "XRP/JPY", "SOL/JPY", "DOGE/JPY", "LINK/JPY",
    ]  # fmt: skip
    assert rows["BTC/JPY（基準）"] == ["10,344,652", "+1.28%", "—"]
    # 対BTC = 24時間の変化率の差（XRP 2.7961% - BTC 1.2834%）
    assert rows["XRP/JPY"] == ["155.661", "+2.80%", "+1.51pt"]
    assert rows["ETH/JPY"][2] == "-0.14pt"
    assert content.basis == [BITBANK_LINE]


def test_unknown_pair_is_skipped_with_warning(fake_bitbank, ctx, caplog):
    fake_bitbank(BITBANK_FIXTURE)
    ctx.watchlist.crypto.watch = ["eth_jpy", "nothing_jpy"]

    with caplog.at_level(logging.WARNING):
        content = build_crypto_watchlist(ctx)

    assert list(_table(content.body, "銘柄")) == ["BTC/JPY（基準）", "ETH/JPY"]
    assert "スキップ: nothing_jpy" in content.body
    assert "nothing_jpy" in caplog.text


def test_market_table_starts_with_btc(fake_bitbank, fake_yfinance, ctx):
    fake_bitbank(BITBANK_FIXTURE)
    fake_yfinance(YF_PRE_OPEN_FIXTURE)

    content = build_markets(ctx)
    rows = _table(content.body, "項目")

    assert next(iter(rows)) == "BTC/JPY ※"
    assert rows["BTC/JPY ※"] == ["10,344,652", "+131,083", "+1.28%"]
    assert content.basis[0] == BITBANK_LINE
    assert content.sources == ["bitbank（bitbank-lab-mcp）", "Yahoo Finance（yfinance）"]


def test_bitbank_is_fetched_once_per_run(fake_bitbank, fake_yfinance, ctx):
    calls = fake_bitbank(BITBANK_FIXTURE)
    fake_yfinance(YF_PRE_OPEN_FIXTURE)

    sections = build_sections(ctx, SECTION_SPECS[1:6])

    assert [s.status for s in sections] == [STATUS_OK] * 5
    assert len(calls) == 1


def test_mcp_failure_is_contained(fake_yfinance, ctx, monkeypatch):
    """接続に失敗したら BTC 系は「取得失敗」、yfinance の欄はそのまま。再接続もしない"""
    attempts = []

    def broken(*args, **kwargs):
        attempts.append(1)
        raise ConnectionError("npx not found")

    monkeypatch.setattr("good_morning.collector.bitbank_mcp.fetch_snapshot", broken)
    fake_yfinance(YF_PRE_OPEN_FIXTURE)

    sections = {s.key: s for s in build_sections(ctx, SECTION_SPECS[1:6])}

    assert sections["btc"].status == STATUS_FAILED
    assert sections["crypto_watchlist"].status == STATUS_FAILED
    assert sections["markets"].status == STATUS_OK
    assert "| BTC/JPY | 取得失敗 |" in sections["markets"].body
    assert sections["sectors"].status == STATUS_OK
    assert len(attempts) == 1


def test_main_pair_missing_fails_watchlist(fake_bitbank, ctx):
    data = copy.deepcopy(load_fixture_json(BITBANK_FIXTURE))
    items = data["results"]["tickers_jpy"]["data"]["items"]
    data["results"]["tickers_jpy"]["data"]["items"] = [i for i in items if i["pair"] != "btc_jpy"]
    fake_bitbank(data)

    with pytest.raises(ValueError, match="btc_jpy"):
        build_crypto_watchlist(ctx)


@pytest.mark.parametrize(
    "text,expected",
    [("10367300", "10,367,300"), ("155.516", "155.516"), ("11747.0", "11,747.0"), ("9.484", "9.484")],
)
def test_format_price_text_keeps_exchange_precision(text, expected):
    assert format_price_text(text) == expected
