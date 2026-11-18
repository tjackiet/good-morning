"""日足から「終値・前日比・前日比%」を計算する（ネットワークに触れない純粋な処理）"""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from good_morning.collector.market_data import DailyBar, DailySeries, MarketDataError
from good_morning.markets.config import Basis, MarketClose, ValueFormat


@dataclass(frozen=True)
class Quote:
    ticker: str
    name: str
    basis: Basis
    format: ValueFormat
    decimals: int
    last: float
    prev: float
    last_date: date
    prev_date: date
    # 確定しているはずの日（last_date より新しい）の終値が取得元で空だった日付。
    # このとき last / prev は1日前の終値（表では「11/16 終値・11/17 は未反映」と出す）
    missing_close: date | None = None

    @property
    def effective_date(self) -> date:
        """本来の基準日（終値が未反映なら、その日）"""
        return self.missing_close or self.last_date

    @property
    def change(self) -> float:
        return self.last - self.prev

    @property
    def change_pct(self) -> float:
        return (self.last / self.prev - 1) * 100

    @property
    def change_bp(self) -> float:
        """利回りの前日比（bp）。値が % 表示なので 1% = 100bp"""
        return self.change * 100


@dataclass(frozen=True)
class QuoteFailure:
    """取得や計算に失敗した銘柄（表では「取得失敗」と表示する）"""

    ticker: str
    name: str
    reason: str


QuoteResult = Quote | QuoteFailure


def is_settled_day(day: date, now: datetime, close: MarketClose) -> bool:
    """その日の NY 終値が確定している時刻を過ぎているか"""
    now_ny = now.astimezone(close.tz)
    return day < now_ny.date() or (day == now_ny.date() and now_ny.time() >= close.settled_time)


def complete_bars(series: DailySeries, now: datetime, close: MarketClose) -> list[DailyBar]:
    """形成中の足を捨て、確定した足だけを返す

    NY の日付で「今日」の足は、NY終値の確定時刻（close + settle）を過ぎるまで形成中とみなす。
    それより先の日付の足（夜間取引で翌営業日の足が出ている場合）も捨てる。
    足の日付は取引所のタイムゾーンでの取引日なので、^TNX（シカゴ）でも NY の日付と比べてよい。
    """
    now_ny = now.astimezone(close.tz)
    today = now_ny.date()
    settled = now_ny.time() >= close.settled_time

    bars = list(series.bars)
    while bars and (bars[-1].date > today or (bars[-1].date == today and not settled)):
        bars.pop()
    return bars


def make_quote(
    series: DailySeries,
    *,
    name: str,
    basis: Basis,
    now: datetime,
    close: MarketClose,
    value_format: ValueFormat = "price",
    decimals: int = 2,
) -> Quote:
    """日足の直近2本から Quote を作る

    basis が close なら確定した足（NY終値）だけを使い、live なら最新の足（取得時点の値）を使う。
    """
    bars = complete_bars(series, now, close) if basis == "close" else list(series.bars)
    if len(bars) < 2:
        raise MarketDataError(
            f"{series.ticker}: 前日比を出すための確定した日足が足りません（{len(bars)}本）"
        )

    prev, last = bars[-2], bars[-1]
    if prev.close == 0:
        raise MarketDataError(f"{series.ticker}: 前日の終値が0のため前日比を計算できません")

    missing = None
    if basis == "close":
        pending = [d for d in series.empty_close_dates if d > last.date and is_settled_day(d, now, close)]
        missing = max(pending) if pending else None

    return Quote(
        ticker=series.ticker,
        name=name,
        basis=basis,
        format=value_format,
        decimals=decimals,
        last=last.close,
        prev=prev.close,
        last_date=last.date,
        prev_date=prev.date,
        missing_close=missing,
    )


def common_close_date(results: list[QuoteResult]) -> date | None:
    """basis: close の銘柄で最も多い「最新の終値の日付」（ヘッダーの基準日に使う）"""
    # 終値が未反映の銘柄は、本来の基準日（未反映の日）で数える
    dates = [r.effective_date for r in results if isinstance(r, Quote) and r.basis == "close"]
    if not dates:
        return None
    counts = Counter(dates)
    # 同数なら新しい日付を優先する
    return max(counts, key=lambda d: (counts[d], d))


def sort_by_change_pct(results: list[QuoteResult]) -> list[QuoteResult]:
    """騰落率の高い順。失敗した銘柄は最後に回す"""
    quotes = sorted(
        (r for r in results if isinstance(r, Quote)), key=lambda q: q.change_pct, reverse=True
    )
    failures = [r for r in results if isinstance(r, QuoteFailure)]
    return [*quotes, *failures]
