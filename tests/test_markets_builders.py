"""マーケット一覧・セクター・株式ウォッチリストのセクション（実データの fixtures で確認）"""

import json
from datetime import date, datetime

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
from good_morning.timeutil import JST
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


def test_markets_table_from_pre_open_snapshot(fake_yfinance, ctx, monkeypatch):
    config = load_markets_config()
    config.optional_groups["index_futures"] = True  # 取得時点の値（先物）の桁数も確かめるため
    monkeypatch.setattr("good_morning.markets.builders.load_markets_config", lambda: config)
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
    # 先頭の BTC/JPY は bitbank（このテストでは接続しないので取得失敗）
    assert list(rows)[1:5] == ["BTC/JPY", "米10年債利回り", "ドル円 ※", "NYダウ"]

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


def test_optional_groups_turned_off_are_not_shown(fake_yfinance, ctx):
    """設定のまま（株価指数先物はオフ）では、先物の行は出ない"""
    fake_yfinance(YF_PRE_OPEN_FIXTURE)

    rows = _rows(build_markets(ctx).body)

    assert not any("先物" in name and name not in ("WTI原油先物 ※", "金先物 ※") for name in rows)
    assert "VIX" in rows and "ドルインデックス ※" in rows


def test_close_basis_line_in_summer_time():
    """夏時間は NY 16:00 = 日本時間 5:00"""
    line = close_basis_line(date(2026, 7, 15), MarketClose())

    assert line.endswith("7/15（水）のNY終値（日本時間 7/16 05:00）")


# --- 取得元が終値を空のまま返したときの取り直しと表示 ------------------------------------

AFTER_CLOSE = datetime(2026, 11, 18, 10, 30, tzinfo=JST)  # = 11/17 20:30 ET（11/17 の終値は確定済み）


@pytest.fixture
def stocks_with_empty_close(monkeypatch):
    """米国株3銘柄に 11/17 の行を足す。fill_after 回目の取得から終値が入る（None なら最後まで空）"""
    data = json.loads((FIXTURES_DIR / YF_PRE_OPEN_FIXTURE).read_text(encoding="utf-8"))
    closes_1117 = {"NVDA": 155.46, "COIN": 115.0, "MSTR": 96.5}
    calls = {}
    sleeps = []
    monkeypatch.setattr("good_morning.markets.builders._sleep", sleeps.append)

    def install(fill_after: int | None, only: set[str] | None = None):
        class FakeTicker:
            def __init__(self, ticker):
                self.ticker = ticker

            def history(self, period=None, interval=None, auto_adjust=None, actions=None):
                from conftest import history_frame

                calls[self.ticker] = calls.get(self.ticker, 0) + 1
                series = json.loads(json.dumps(data["series"][self.ticker]))
                filled = fill_after is not None and calls[self.ticker] >= fill_after
                if only is not None and self.ticker not in only:
                    filled = False
                value = closes_1117[self.ticker] if filled else None
                series["rows"].append(["2026-11-17T00:00:00-05:00", value])
                return history_frame(series)

        monkeypatch.setattr("good_morning.collector.market_data.yf.Ticker", FakeTicker)
        return calls, sleeps

    return install


def _ctx_after_close():
    from good_morning.paths import CONFIG_DIR as _CONFIG_DIR

    return RunContext(now=AFTER_CLOSE, watchlist=load_watchlist(_CONFIG_DIR))


def test_empty_close_is_fetched_again_and_filled(stocks_with_empty_close):
    calls, sleeps = stocks_with_empty_close(fill_after=2)  # 2回目の取得で終値が入る

    content = build_stock_watchlist(_ctx_after_close())
    rows = _rows(content.body)

    assert sleeps == [20]  # 1回だけ待って取り直した
    assert calls == {"NVDA": 2, "COIN": 2, "MSTR": 2}
    assert rows["エヌビディア（NVDA）"] == ["155.46", "-0.68", "-0.44%"]  # 11/17 の終値で計算
    assert "未反映" not in content.body
    assert content.basis[0].startswith("米国市場（株・指数・ETF・金利）: 11/17（火）のNY終値")


def test_still_empty_close_is_shown_with_note(stocks_with_empty_close):
    _, sleeps = stocks_with_empty_close(fill_after=None)  # 最後まで空

    content = build_stock_watchlist(_ctx_after_close())
    rows = _rows(content.body)

    assert sleeps == [20, 20]  # 設定どおり2回取り直した
    # 全行が同じく未反映なので、行ごとの注記は省き、表の下に1回だけ書く
    assert rows["エヌビディア（NVDA）"] == ["156.14", "-6.71", "-4.12%"]
    assert "⚠ この表はすべて 11/16 の終値と前日比です（11/17 の終値が取得元にまだ反映されていません）" in content.body
    # 本来の基準日（11/17）をヘッダーに出し、行ごとに未反映と注記する
    assert content.basis[0].startswith("米国市場（株・指数・ETF・金利）: 11/17（火）のNY終値")


def test_facts_tell_claude_the_close_is_missing(stocks_with_empty_close):
    from good_morning.synthesis.facts import build_facts

    stocks_with_empty_close(fill_after=None)
    ctx = _ctx_after_close()
    build_stock_watchlist(ctx)

    facts = build_facts(ctx)

    assert "エヌビディア（NVDA）（11/16 終値。11/17 の終値は取得元に未反映）: 156.14" in facts


def test_partly_empty_closes_are_noted_per_row(stocks_with_empty_close):
    """一部の銘柄だけ未反映なら、その行に注記する"""
    stocks_with_empty_close(fill_after=1, only={"NVDA"})  # NVDA だけ最初から終値が入る

    content = build_stock_watchlist(_ctx_after_close())
    rows = _rows(content.body)

    assert "エヌビディア（NVDA）" in rows
    assert "コインベース（COIN）（11/16 終値・11/17 は未反映）" in rows
    assert "⚠ 取得元にまだ 11/17 の終値が反映されていない銘柄は" in content.body


# --- まとめ（Claude）で前の営業日の終値に日付を添える -------------------------------------


@pytest.fixture
def stale_ctx(stocks_with_empty_close):
    stocks_with_empty_close(fill_after=None)  # 3銘柄とも 11/17 の終値が最後まで空
    ctx = _ctx_after_close()
    build_stock_watchlist(ctx)
    return ctx


def test_stale_values_come_from_quotes_with_missing_close(stale_ctx):
    from datetime import date

    from good_morning.synthesis.stale import stale_values

    values = {v.label: v for v in stale_values(stale_ctx)}

    assert set(values) == {"NVDA", "COIN", "MSTR"}
    assert values["NVDA"].close_date == date(2026, 11, 16)
    assert values["NVDA"].numbers == {"156.14", "4.12"}  # 終値と前日比%


@pytest.mark.parametrize(
    "text,expected",
    [
        # 2026-11-18 の実際の出力: 日付がないので末尾に添える
        (
            "暗号資産関連株はCOIN-6.12%、MSTR-7.70%、NVDA-4.12%と大幅下落した。",
            "暗号資産関連株はCOIN-6.12%、MSTR-7.70%、NVDA-4.12%と大幅下落した（COIN・MSTR・NVDA は 11/16 終値）。",
        ),
        # 日付があれば（「月日」の書き方も）そのまま
        ("NVDA-4.12%（いずれも11/16終値）と下落した。", "NVDA-4.12%（いずれも11/16終値）と下落した。"),
        ("NVDAは11月16日に4.12%下落した。", "NVDAは11月16日に4.12%下落した。"),
        # 未反映の銘柄の数値がなければそのまま
        ("S&P500は-1.03%下落した。", "S&P500は-1.03%下落した。"),
        # 句点がなければ末尾に足す
        ("NVDA は 156.14ドル", "NVDA は 156.14ドル（NVDA は 11/16 終値）"),
    ],
)
def test_annotate_stale_dates(stale_ctx, text, expected):
    from good_morning.synthesis.stale import annotate_stale_dates, stale_values

    assert annotate_stale_dates(text, stale_values(stale_ctx)) == expected


def test_synthesis_lines_get_dates_but_btc_comment_is_left_alone(stale_ctx):
    from good_morning.synthesis.claude import Synthesis, add_stale_dates

    result = Synthesis(
        stance="リスクオフ",
        summary_lines=["一行目。", "NVDA-4.12%と大幅下落した。", "三行目。"],
        btc_comment="RSI は 4.12 ではない話。",
        bullish=["強気。"],
        bearish=["COIN-6.12%の下落。"],
        conclusion="まとめ。",
    )

    add_stale_dates(result, stale_ctx)

    assert result.summary_lines[1] == "NVDA-4.12%と大幅下落した（NVDA は 11/16 終値）。"
    assert result.bearish == ["COIN-6.12%の下落（COIN は 11/16 終値）。"]
    assert result.btc_comment == "RSI は 4.12 ではない話。"  # テクニカルの話は見ない
    assert result.summary_lines[0] == "一行目。"


def test_facts_mark_stale_sectors(stocks_with_empty_close, monkeypatch):
    """セクターも未反映なら、Claude に渡すデータに日付と未反映を書く"""
    from good_morning.synthesis.facts import _sectors

    stocks_with_empty_close(fill_after=None)
    ctx = _ctx_after_close()
    build_stock_watchlist(ctx)
    ctx.data["sectors"] = ctx.data["stock_watchlist"]  # 同じ Quote で形だけ確かめる

    lines = _sectors(ctx)

    assert lines[1].endswith("（11/16 終値。11/17 の終値は取得元に未反映）")
