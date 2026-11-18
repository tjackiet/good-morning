"""マーケット一覧・セクター別騰落率・株式ウォッチリストの Markdown の表"""

from datetime import date, datetime

from good_morning.markets.config import MarketClose
from good_morning.markets.quotes import Quote, QuoteFailure, QuoteResult
from good_morning.timeutil import JST, format_jst, format_month_day

FAILED = "取得失敗"
NONE = "—"
LIVE_MARK = "※"


def format_value(q: Quote) -> str:
    if q.format == "yield":
        return f"{q.last:.{q.decimals}f}%"
    return f"{q.last:,.{q.decimals}f}"


def format_change(q: Quote) -> str:
    if q.format == "yield":
        return f"{q.change_bp:+.1f}bp"
    return f"{q.change:+,.{q.decimals}f}"


def format_change_pct(q: Quote) -> str:
    # 利回りの変化率（% の %）は意味が薄いので出さない。前日比の bp で見る
    if q.format == "yield":
        return NONE
    return f"{q.change_pct:+.2f}%"


def uniform_stale(results: list[QuoteResult]) -> bool:
    """表のすべての銘柄で、同じ日の終値が未反映か（そのときは行ごとの注記をやめ、表の下に1回だけ書く）"""
    keys = {(r.last_date, r.missing_close) for r in results if isinstance(r, Quote)}
    return len(keys) == 1 and next(iter(keys))[1] is not None


def date_note(q: Quote, base_date: date | None, skip_stale: bool = False) -> str | None:
    """終値の日付の注記（なければ None）

    - 取得元で最新の終値が空だった: 「11/16 終値・11/17 は未反映」（skip_stale なら出さない）
    - 祝日などで他の銘柄と終値の日付がずれている: 「11/13 終値」
    """
    if q.basis != "close":
        return None
    last = f"{q.last_date.month}/{q.last_date.day}"
    if q.missing_close is not None:
        if skip_stale:
            return None
        return f"{last} 終値・{q.missing_close.month}/{q.missing_close.day} は未反映"
    if base_date is not None and q.last_date != base_date:
        return f"{last} 終値"
    return None


def _label(
    result: QuoteResult, base_date: date | None, show_ticker: bool, skip_stale: bool = False
) -> str:
    label = f"{result.name}（{result.ticker}）" if show_ticker else result.name
    if isinstance(result, Quote):
        if result.basis == "live":
            label += f" {LIVE_MARK}"
        elif note := date_note(result, base_date, skip_stale):
            label += f"（{note}）"
    return label


def stale_note(results: list[QuoteResult]) -> str | None:
    """終値が未反映の銘柄があるときに、表の下に添える注意書き"""
    days = sorted({r.missing_close for r in results if isinstance(r, Quote) and r.missing_close})
    if not days:
        return None
    if uniform_stale(results):
        q = next(r for r in results if isinstance(r, Quote))
        return (
            f"⚠ この表はすべて {q.last_date.month}/{q.last_date.day} の終値と前日比です"
            f"（{days[0].month}/{days[0].day} の終値が取得元にまだ反映されていません）。"
        )
    labels = "・".join(f"{d.month}/{d.day}" for d in days)
    return (
        f"⚠ 取得元にまだ {labels} の終値が反映されていない銘柄は、前の営業日の終値と前日比を表示しています"
        "（注記のある行）。"
    )


def render_market_table(results: list[QuoteResult], base_date: date | None) -> str:
    skip = uniform_stale(results)
    lines = ["| 項目 | 終値 | 前日比 | 前日比% |", "|---|---:|---:|---:|"]
    for r in results:
        label = _label(r, base_date, show_ticker=False, skip_stale=skip)
        if isinstance(r, QuoteFailure):
            lines.append(f"| {label} | {FAILED} | {NONE} | {NONE} |")
        else:
            lines.append(
                f"| {label} | {format_value(r)} | {format_change(r)} | {format_change_pct(r)} |"
            )
    return "\n".join(lines)


def render_sector_table(results: list[QuoteResult], base_date: date | None) -> str:
    """results は騰落率順に並べ替え済みであること"""
    skip = uniform_stale(results)
    lines = ["| 順位 | セクター | 騰落率 | 終値 |", "|---:|---|---:|---:|"]
    rank = 0
    for r in results:
        label = _label(r, base_date, show_ticker=True, skip_stale=skip)
        if isinstance(r, QuoteFailure):
            lines.append(f"| {NONE} | {label} | {FAILED} | {NONE} |")
        else:
            rank += 1
            lines.append(f"| {rank} | {label} | {format_change_pct(r)} | {format_value(r)} |")
    return "\n".join(lines)


def render_stock_table(results: list[QuoteResult], base_date: date | None) -> str:
    """results は騰落率順に並べ替え済みであること（単位はドル）"""
    skip = uniform_stale(results)
    lines = ["| 銘柄 | 終値 | 前日比 | 騰落率 |", "|---|---:|---:|---:|"]
    for r in results:
        label = _label(r, base_date, show_ticker=True, skip_stale=skip)
        if isinstance(r, QuoteFailure):
            lines.append(f"| {label} | {FAILED} | {NONE} | {NONE} |")
        else:
            lines.append(
                f"| {label} | {format_value(r)} | {format_change(r)} | {format_change_pct(r)} |"
            )
    return "\n".join(lines)


def close_basis_line(base_date: date, close: MarketClose) -> str:
    """ヘッダーの「データ基準時刻」に載せる NY終値の行（JST の時刻を併記）"""
    close_at = datetime.combine(base_date, close.close_time, tzinfo=close.tz).astimezone(JST)
    return (
        f"米国市場（株・指数・ETF・金利）: {format_month_day(base_date)}のNY終値"
        f"（日本時間 {close_at.month}/{close_at.day} {close_at:%H:%M}）"
    )


def live_basis_line(fetched_at: datetime) -> str:
    return f"為替・先物など（表の{LIVE_MARK}）: 取得時点の値（{format_jst(fetched_at)}）"
