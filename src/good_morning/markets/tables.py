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


def _label(result: QuoteResult, base_date: date | None, show_ticker: bool) -> str:
    label = f"{result.name}（{result.ticker}）" if show_ticker else result.name
    if isinstance(result, Quote):
        if result.basis == "live":
            label += f" {LIVE_MARK}"
        elif base_date is not None and result.last_date != base_date:
            # 祝日などで他の銘柄と終値の日付がずれているときは日付を添える
            label += f"（{result.last_date.month}/{result.last_date.day} 終値）"
    return label


def render_market_table(results: list[QuoteResult], base_date: date | None) -> str:
    lines = ["| 項目 | 終値 | 前日比 | 前日比% |", "|---|---:|---:|---:|"]
    for r in results:
        label = _label(r, base_date, show_ticker=False)
        if isinstance(r, QuoteFailure):
            lines.append(f"| {label} | {FAILED} | {NONE} | {NONE} |")
        else:
            lines.append(
                f"| {label} | {format_value(r)} | {format_change(r)} | {format_change_pct(r)} |"
            )
    return "\n".join(lines)


def render_sector_table(results: list[QuoteResult], base_date: date | None) -> str:
    """results は騰落率順に並べ替え済みであること"""
    lines = ["| 順位 | セクター | 騰落率 | 終値 |", "|---:|---|---:|---:|"]
    rank = 0
    for r in results:
        label = _label(r, base_date, show_ticker=True)
        if isinstance(r, QuoteFailure):
            lines.append(f"| {NONE} | {label} | {FAILED} | {NONE} |")
        else:
            rank += 1
            lines.append(f"| {rank} | {label} | {format_change_pct(r)} | {format_value(r)} |")
    return "\n".join(lines)


def render_stock_table(results: list[QuoteResult], base_date: date | None) -> str:
    """results は騰落率順に並べ替え済みであること（単位はドル）"""
    lines = ["| 銘柄 | 終値 | 前日比 | 騰落率 |", "|---|---:|---:|---:|"]
    for r in results:
        label = _label(r, base_date, show_ticker=True)
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
