"""good_morning.collector.market_data のテスト（yfinance の結果の変換）"""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from conftest import YF_PRE_OPEN_FIXTURE

from good_morning.collector.market_data import (
    MarketDataError,
    fetch_daily_series,
    series_from_history,
)


def test_fetch_daily_series_from_real_fixture(fake_yfinance):
    fake_yfinance(YF_PRE_OPEN_FIXTURE)

    series = fetch_daily_series("^TNX")

    assert series.ticker == "^TNX"
    assert series.timezone == "America/Chicago"
    # 足の日付は取引所のタイムゾーンでの取引日
    assert [b.date for b in series.bars[-3:]] == [
        date(2026, 11, 13),
        date(2026, 11, 16),
        date(2026, 11, 17),
    ]
    assert series.bars[-2].close == pytest.approx(5.121)


def test_unknown_ticker_raises(fake_yfinance):
    fake_yfinance(YF_PRE_OPEN_FIXTURE)

    with pytest.raises(MarketDataError, match="BOGUS"):
        fetch_daily_series("BOGUS")


def test_exception_from_yfinance_is_wrapped(monkeypatch):
    class Boom:
        def __init__(self, ticker):
            pass

        def history(self, **kwargs):
            raise ConnectionError("network down")

    monkeypatch.setattr("good_morning.collector.market_data.yf.Ticker", Boom)

    with pytest.raises(MarketDataError, match="ConnectionError"):
        fetch_daily_series("^GSPC")


def test_series_from_history_drops_missing_closes():
    """yfinance は当日の行を NaN で返すことがある。欠損は捨てる"""
    index = pd.to_datetime(["2026-11-13", "2026-11-16", "2026-11-17"]).tz_localize(
        "America/New_York"
    )
    history = pd.DataFrame({"Close": [100.0, 101.0, np.nan]}, index=index)

    series = series_from_history("X", history)

    assert [b.close for b in series.bars] == [100.0, 101.0]


def test_series_from_history_rejects_empty():
    with pytest.raises(MarketDataError):
        series_from_history("X", pd.DataFrame())
