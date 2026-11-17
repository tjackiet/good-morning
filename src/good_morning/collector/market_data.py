"""日足の取得（yfinance に触れるのはこのファイルだけ）

yfinance は非公式ライブラリなので、取得元を差し替えるときはこのファイルだけを
直せばよいようにしておく。ここから外へは pandas の型を出さず、DailySeries だけを返す。

取得するのは日足 history(interval="1d") の終値だけ。info の currentPrice 系は使わない
（大原則2: JST 7:00 は米国の時間外取引の最中で、時間外の値が混ざるため）。
形成中の足を捨てるかどうかは呼び出し側（good_morning.markets.quotes）が決める。
"""

import logging
from dataclasses import dataclass
from datetime import date

import yfinance as yf

logger = logging.getLogger(__name__)

# 前日比には確定した足が2本あればよいが、連休や祝日をまたいでも足りるように長めに取る
HISTORY_PERIOD = "1mo"


class MarketDataError(Exception):
    """日足を取得できなかった、または前日比を出せなかった"""


@dataclass(frozen=True)
class DailyBar:
    date: date  # 取引日（取引所のタイムゾーンでの日付）
    close: float


@dataclass(frozen=True)
class DailySeries:
    ticker: str
    timezone: str  # 取引所のタイムゾーン（例: America/New_York）
    bars: tuple[DailyBar, ...]  # 古い順


def series_from_history(ticker: str, history) -> DailySeries:
    """yfinance の history() の結果（DataFrame）を DailySeries に変換する"""
    if history is None or history.empty or "Close" not in history:
        raise MarketDataError(f"{ticker}: 日足データが空です（銘柄コードの誤りか、取得元の不調）")

    closes = history["Close"].dropna()
    if closes.empty:
        raise MarketDataError(f"{ticker}: 終値がすべて欠損しています")

    timezone = str(closes.index.tz) if closes.index.tz is not None else "UTC"
    bars = tuple(DailyBar(date=ts.date(), close=float(value)) for ts, value in closes.items())
    return DailySeries(ticker=ticker, timezone=timezone, bars=bars)


def fetch_daily_series(ticker: str, period: str = HISTORY_PERIOD) -> DailySeries:
    """1銘柄の日足（終値）を取得する"""
    try:
        history = yf.Ticker(ticker).history(
            period=period, interval="1d", auto_adjust=False, actions=False
        )
    except Exception as e:
        raise MarketDataError(f"{ticker}: 取得に失敗しました（{type(e).__name__}: {e}）") from e
    return series_from_history(ticker, history)
