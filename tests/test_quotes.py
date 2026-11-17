"""good_morning.markets.quotes のテスト（形成中の足の扱いと前日比）"""

from datetime import date, datetime

import pytest

from good_morning.collector.market_data import DailyBar, DailySeries, MarketDataError
from good_morning.markets.config import MarketClose
from good_morning.markets.quotes import (
    Quote,
    QuoteFailure,
    common_close_date,
    complete_bars,
    make_quote,
    sort_by_change_pct,
)
from good_morning.timeutil import JST

CLOSE = MarketClose()  # 16:00 ET、確定まで +30分

# 11/13（金）, 11/16（月）, 11/17（火）の3本
SERIES = DailySeries(
    ticker="^TNX",
    timezone="America/Chicago",
    bars=(
        DailyBar(date(2026, 11, 13), 5.154),
        DailyBar(date(2026, 11, 16), 5.121),
        DailyBar(date(2026, 11, 17), 5.141),
    ),
)


def _jst(*args) -> datetime:
    return datetime(*args, tzinfo=JST)


@pytest.mark.parametrize(
    "now,expected_last",
    [
        # 11/17 22:50 JST = 11/17 08:50 ET（取引開始前）→ 11/17 の足は形成中なので捨てる
        (_jst(2026, 11, 17, 22, 50), date(2026, 11, 16)),
        # 11/18 06:20 JST = 11/17 16:20 ET（終値の確定待ち）→ まだ捨てる
        (_jst(2026, 11, 18, 6, 20), date(2026, 11, 16)),
        # 11/18 07:15 JST = 11/17 17:15 ET（定時実行の時刻）→ 11/17 の終値は確定
        (_jst(2026, 11, 18, 7, 15), date(2026, 11, 17)),
        # 週末（11/21 土）は金曜までの足をそのまま使う
        (_jst(2026, 11, 21, 7, 15), date(2026, 11, 17)),
    ],
)
def test_complete_bars_drops_forming_bar(now, expected_last):
    assert complete_bars(SERIES, now, CLOSE)[-1].date == expected_last


def test_complete_bars_drops_bar_dated_after_ny_today():
    """夜間取引で翌営業日の日付の足が出ていても捨てる"""
    series = DailySeries("X", "America/New_York", (*SERIES.bars, DailyBar(date(2026, 11, 18), 1)))

    bars = complete_bars(series, _jst(2026, 11, 18, 7, 15), CLOSE)

    assert bars[-1].date == date(2026, 11, 17)


def test_complete_bars_handles_summer_time():
    """夏時間（EDT）でも NY の 16:30 を境にする: 7/15 17:00 JST = 7/15 04:00 EDT"""
    series = DailySeries(
        "X", "America/New_York", (DailyBar(date(2026, 7, 14), 1), DailyBar(date(2026, 7, 15), 2))
    )

    assert complete_bars(series, _jst(2026, 7, 15, 17, 0), CLOSE)[-1].date == date(2026, 7, 14)
    # 7/16 05:30 JST = 7/15 16:30 EDT → 確定
    assert complete_bars(series, _jst(2026, 7, 16, 5, 30), CLOSE)[-1].date == date(2026, 7, 15)


def test_make_quote_close_basis_uses_confirmed_closes():
    q = make_quote(
        SERIES,
        name="米10年債利回り",
        basis="close",
        now=_jst(2026, 11, 17, 22, 50),
        close=CLOSE,
        value_format="yield",
        decimals=3,
    )

    assert (q.last, q.prev) == (5.121, 5.154)
    assert q.last_date == date(2026, 11, 16)
    assert q.change_bp == pytest.approx(-3.3)


def test_make_quote_live_basis_uses_latest_bar():
    q = make_quote(SERIES, name="x", basis="live", now=_jst(2026, 11, 17, 22, 50), close=CLOSE)

    assert (q.last, q.prev) == (5.141, 5.121)
    assert q.change_pct == pytest.approx((5.141 / 5.121 - 1) * 100)


def test_make_quote_requires_two_confirmed_bars():
    series = DailySeries("X", "America/New_York", SERIES.bars[1:])  # 11/16 と 11/17（形成中）

    with pytest.raises(MarketDataError, match="足りません"):
        make_quote(series, name="x", basis="close", now=_jst(2026, 11, 17, 22, 50), close=CLOSE)


def _quote(ticker, pct, last_date=date(2026, 11, 16), basis="close"):
    return Quote(ticker, ticker, basis, "price", 2, 100 + pct, 100.0, last_date, date(2026, 11, 13))


def test_common_close_date_picks_majority_and_ignores_live():
    results = [
        _quote("A", 1),
        _quote("B", 1),
        _quote("C", 1, last_date=date(2026, 11, 13)),
        _quote("D", 1, last_date=date(2026, 11, 17), basis="live"),
        QuoteFailure("E", "E", "x"),
    ]

    assert common_close_date(results) == date(2026, 11, 16)
    assert common_close_date([QuoteFailure("E", "E", "x")]) is None


def test_sort_by_change_pct_puts_failures_last():
    results = [_quote("A", -1.0), QuoteFailure("F", "F", "x"), _quote("B", 2.0), _quote("C", 0.5)]

    assert [r.ticker for r in sort_by_change_pct(results)] == ["B", "C", "A", "F"]
