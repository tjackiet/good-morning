"""日足の取得（yfinance に触れるのはこのファイルだけ）

yfinance は非公式ライブラリなので、取得元を差し替えるときはこのファイルだけを
直せばよいようにしておく。ここから外へは pandas の型を出さず、DailySeries だけを返す。

取得するのは日足 history(interval="1d") の終値だけ。info の currentPrice 系は使わない
（大原則2: JST 7:00 は米国の時間外取引の最中で、時間外の値が混ざるため）。
形成中の足を捨てるかどうかは呼び出し側（good_morning.markets.quotes）が決める。
"""

import logging
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

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


# --- 決算日 -------------------------------------------------------------------
#
# 決算日は info の earningsTimestampStart / isEarningsDateEstimate（確定か推定か）と、
# get_earnings_dates() の行（日時と EPS 予想）から決める。info を使うのは決算日の情報だけで、
# 価格（currentPrice 系）には使わない（大原則2）。
# 実データで確認した info の意味（2026-11-17）:
#   isEarningsDateEstimate=False かつ未来の日時 … 確定した次回の決算
#   isEarningsDateEstimate=True                 … 推定の次回の決算（Start〜End が推定の範囲）
#   isEarningsDateEstimate=False かつ過去の日時 … 前回の決算（次回は未発表）

EARNINGS_DATES_LIMIT = 8


@dataclass(frozen=True)
class EarningsRow:
    when: datetime  # タイムゾーン付き
    eps_estimate: float | None
    reported_eps: float | None


@dataclass(frozen=True)
class EarningsInfo:
    ticker: str
    next_start: datetime | None  # info の earningsTimestampStart（なければ earningsTimestamp）
    next_end: datetime | None
    is_estimate: bool | None
    rows: tuple[EarningsRow, ...]  # get_earnings_dates() の行（新しい順）
    short_name: str | None = None  # 会社名（related の関連企業の表示に使う）


def _timestamp(value) -> datetime | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, tz=UTC)
    return None


def _float_or_none(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def earnings_from_raw(ticker: str, info: dict | None, earnings_dates) -> EarningsInfo:
    """yfinance の info と get_earnings_dates() の結果から EarningsInfo を作る"""
    info = info or {}
    rows: list[EarningsRow] = []
    if earnings_dates is not None and not earnings_dates.empty:
        for ts, row in earnings_dates.iterrows():
            rows.append(
                EarningsRow(
                    when=ts.to_pydatetime(),
                    eps_estimate=_float_or_none(row.get("EPS Estimate")),
                    reported_eps=_float_or_none(row.get("Reported EPS")),
                )
            )
    estimate = info.get("isEarningsDateEstimate")
    return EarningsInfo(
        ticker=ticker,
        next_start=_timestamp(info.get("earningsTimestampStart") or info.get("earningsTimestamp")),
        next_end=_timestamp(info.get("earningsTimestampEnd")),
        is_estimate=estimate if isinstance(estimate, bool) else None,
        rows=tuple(rows),
        short_name=info.get("shortName") or None,
    )


def fetch_earnings(ticker: str) -> EarningsInfo:
    """1銘柄の決算日の情報を取得する"""
    yf_ticker = yf.Ticker(ticker)
    try:
        info = yf_ticker.info
    except Exception as e:
        raise MarketDataError(f"{ticker}: 決算日の情報を取得できません（{type(e).__name__}: {e}）") from e
    try:
        earnings_dates = yf_ticker.get_earnings_dates(limit=EARNINGS_DATES_LIMIT)
    except Exception as e:  # noqa: BLE001 - info だけでも決算日は分かるので続ける
        logger.warning("%s: get_earnings_dates に失敗 - %s: %s", ticker, type(e).__name__, e)
        earnings_dates = None
    return earnings_from_raw(ticker, info, earnings_dates)
