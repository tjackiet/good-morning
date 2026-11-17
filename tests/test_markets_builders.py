"""マーケット一覧・セクター・株式ウォッチリストのセクション（実データの fixtures で確認）"""

import json
from datetime import date

import pytest
from conftest import FIXTURES_DIR, YF_PRE_OPEN_CAPTURED_AT, YF_PRE_OPEN_FIXTURE

from good_morning.collector.market_data import MarketDataError
from good_morning.context import RunContext
from good_morning.markets.builders import build_markets, build_sectors, build_stock_watchlist
from good_morning.markets.config import MarketClose, load_markets_config
from good_morning.markets.tables import close_basis_line
from good_morning.paths import CONFIG_DIR
from good_morning.reporter.markdown import STATUS_FAILED
from good_morning.sections import SectionSpec, build_section
from good_morning.watchlist import load_watchlist

NY_CLOSE_LINE = "米国市場（株・指数・ETF・金利）: 11/16（月）のNY終値（日本時間 11/17 06:00）"


@pytest.fixture
def ctx():
    return RunContext(now=YF_PRE_OPEN_CAPTURED_AT, watchlist=load_watchlist(CONFIG_DIR))


def _rows(body: str) -> dict[str, list[str]]:
    """Markdown の表を {1列目: [残りの列]} にする"""
    rows = {}
    for line in body.splitlines():
        if line.startswith("|") and not line.startswith("|---"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows[cells[0]] = cells[1:]
    return rows


def test_markets_table_from_pre_open_snapshot(fake_yfinance, ctx):
    fake_yfinance(YF_PRE_OPEN_FIXTURE)

    content = build_markets(ctx)
    rows = _rows(content.body)

    # 終値の銘柄: 11/17 の形成中の足を捨て、11/16 の NY終値と 11/13 を比べる
    assert rows["米10年債利回り"] == ["5.121%", "-3.3bp", "—"]
    assert rows["S&P500"] == ["7,416.59", "-145.08", "-1.92%"]
    assert rows["NYダウ"][2] == "-1.41%"
    assert rows["VIX"] == ["22.91", "+3.61", "+18.70%"]
    # 取得時点の銘柄: 最新の足（11/17）と前日の足を比べ、※ を付ける
    assert rows["ドル円 ※"] == ["159.38", "-0.40", "-0.25%"]
    assert rows["S&P500先物 ※"] == ["7,422.75", "-16.25", "-0.22%"]
    assert rows["NYダウ先物 ※"] == ["51,213", "-457", "-0.88%"]  # decimals: 0
    # 並びは markets.yaml の順
    assert list(rows)[1:4] == ["米10年債利回り", "ドル円 ※", "NYダウ"]

    assert content.basis[0] == NY_CLOSE_LINE
    assert content.basis[1] == "為替・先物など（表の※）: 取得時点の値（2026-11-17 22:50 JST）"
    assert content.sources == ["Yahoo Finance（yfinance）"]
    assert "markets" in ctx.data


def test_failed_ticker_shows_row_as_failed(fake_yfinance, ctx, caplog):
    data = json.loads((FIXTURES_DIR / YF_PRE_OPEN_FIXTURE).read_text(encoding="utf-8"))
    del data["series"]["GC=F"]
    fake_yfinance(data)

    content = build_markets(ctx)

    assert _rows(content.body)["金先物"] == ["取得失敗", "—", "—"]
    assert "GC=F" in caplog.text


def test_all_failed_marks_section_failed(fake_yfinance, ctx):
    fake_yfinance({"series": {}})

    with pytest.raises(MarketDataError):
        build_markets(ctx)
    section = build_section(SectionSpec("markets", "マーケット一覧", 1, build_markets), ctx)
    assert section.status == STATUS_FAILED


def test_sectors_ranked_by_change(fake_yfinance, ctx):
    fake_yfinance(YF_PRE_OPEN_FIXTURE)

    content = build_sectors(ctx)
    rows = [r for r in _rows(content.body).items() if r[0] != "順位"]

    assert len(rows) == 11
    ranks = [int(rank) for rank, _ in rows]
    pcts = [float(cells[1].rstrip("%")) for _, cells in rows]
    assert ranks == list(range(1, 12))
    assert pcts == sorted(pcts, reverse=True)
    assert content.basis == [NY_CLOSE_LINE]


def test_stock_watchlist_ranked_by_change(fake_yfinance, ctx):
    fake_yfinance(YF_PRE_OPEN_FIXTURE)

    content = build_stock_watchlist(ctx)
    rows = _rows(content.body)

    assert list(rows)[1:] == ["エヌビディア（NVDA）", "コインベース（COIN）", "ストラテジー（MSTR）"]
    assert rows["エヌビディア（NVDA）"] == ["156.14", "-6.71", "-4.12%"]
    assert rows["ストラテジー（MSTR）"][2] == "-7.70%"
    assert content.basis == [NY_CLOSE_LINE]


def test_stock_watchlist_requires_watchlist(ctx):
    ctx.watchlist = None

    with pytest.raises(ValueError):
        build_stock_watchlist(ctx)


def test_close_date_mismatch_is_annotated(fake_yfinance, ctx):
    """祝日などで終値の日付が他とずれた銘柄には日付を添える"""
    data = json.loads((FIXTURES_DIR / YF_PRE_OPEN_FIXTURE).read_text(encoding="utf-8"))
    tnx = data["series"]["^TNX"]
    tnx["rows"] = [r for r in tnx["rows"] if not r[0].startswith(("2026-11-16", "2026-11-17"))]
    fake_yfinance(data)

    rows = _rows(build_markets(ctx).body)

    assert "米10年債利回り（11/13 終値）" in rows


def test_optional_groups_can_be_turned_off(fake_yfinance, ctx, monkeypatch):
    config = load_markets_config()
    config.optional_groups["index_futures"] = False
    monkeypatch.setattr("good_morning.markets.builders.load_markets_config", lambda: config)
    fake_yfinance(YF_PRE_OPEN_FIXTURE)

    rows = _rows(build_markets(ctx).body)

    assert "S&P500先物 ※" not in rows
    assert "VIX" in rows


def test_close_basis_line_in_summer_time():
    """夏時間は NY 16:00 = 日本時間 5:00"""
    line = close_basis_line(date(2026, 7, 15), MarketClose())

    assert line.endswith("7/15（水）のNY終値（日本時間 7/16 05:00）")
