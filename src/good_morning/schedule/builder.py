"""「今後の予定」のセクション

3つの取得元（events.yaml・FRED・決算）は独立して扱い、どれかが失敗しても
残りで表を作る。失敗した取得元はセクションの末尾に「取得できなかった」と書き、理由はログに残す。
"""

import logging
from datetime import datetime, timedelta

from good_morning.collector import fred, market_data
from good_morning.context import RunContext, SectionContent
from good_morning.schedule.config import EventsConfig, load_events_config
from good_morning.schedule.events import (
    ScheduledEvent,
    fred_events,
    next_earnings_event,
    split_by_detail,
    static_events,
    within_window,
)
from good_morning.timeutil import JST, format_month_day

logger = logging.getLogger(__name__)

SOURCE_FRED = "FRED（セントルイス連銀）"
SOURCE_OFFICIAL = "FRB・日本銀行の公式日程（events.yaml に転記）"
SOURCE_EARNINGS = "Yahoo Finance（yfinance、決算日）"


def _earnings_targets(
    ctx: RunContext, config: EventsConfig
) -> list[tuple[str, str | None, str]]:
    """(ticker, 表示名, 重要度) の一覧。ウォッチリストの銘柄と related の関連企業（重複なし）

    related の表示名は None にしておき、取得した会社名（shortName）を使う。
    """
    if ctx.watchlist is None:
        return []
    targets, seen = [], set()
    for stock in ctx.watchlist.stocks:
        if stock.ticker not in seen:
            seen.add(stock.ticker)
            targets.append((stock.ticker, stock.name, config.earnings.importance.watchlist))
    for stock in ctx.watchlist.stocks:
        for related in stock.related:
            if related not in seen:
                seen.add(related)
                targets.append((related, None, config.earnings.importance.related))
    return targets


def collect_events(
    ctx: RunContext, config: EventsConfig
) -> tuple[list[ScheduledEvent], list[str], list[str]]:
    """(予定, 使えた取得元, 取得できなかったものの説明) を返す"""
    events: list[ScheduledEvent] = []
    sources: list[str] = []
    problems: list[str] = []

    events.extend(static_events(config))
    sources.append(SOURCE_OFFICIAL)

    today = ctx.now.astimezone(JST).date()
    try:
        release_dates = fred.fetch_release_dates(
            today, today + timedelta(days=config.horizon.total_days + 1)
        )
        events.extend(fred_events(release_dates, config.fred))
        sources.append(SOURCE_FRED)
    except Exception as e:  # noqa: BLE001 - FRED が使えなくても残りで表を作る
        logger.warning("今後の予定（FRED）: 取得失敗 - %s", e)
        problems.append(f"米経済指標（FRED）: {e}")

    failed_tickers = []
    targets = _earnings_targets(ctx, config)
    for ticker, name, importance in targets:
        try:
            info = market_data.fetch_earnings(ticker)
            display = name or info.short_name or ticker
            event = next_earnings_event(info, name=display, importance=importance, now=ctx.now)
            if event is not None:
                events.append(event)
        except Exception as e:  # noqa: BLE001 - 1銘柄の失敗で止めない
            logger.warning("今後の予定（決算 %s）: 取得失敗 - %s", ticker, e)
            failed_tickers.append(ticker)
    if targets and len(failed_tickers) < len(targets):
        sources.append(SOURCE_EARNINGS)
    if failed_tickers:
        problems.append(f"決算日: {', '.join(failed_tickers)}")

    return events, sources, problems


def _when_label(e: ScheduledEvent) -> str:
    if e.when is None:
        return f"{format_month_day(e.day)}"
    return f"{format_month_day(e.day)} {e.when:%H:%M}"


def _title_label(e: ScheduledEvent) -> str:
    extras = []
    if e.estimated:
        extras.append("日付は推定")
    if e.note:
        extras.append(e.note)
    return f"{e.title}（{'・'.join(extras)}）" if extras else e.title


def render_detail_table(events: list[ScheduledEvent]) -> str:
    lines = ["| 日時（日本時間） | 内容 | 重要度 | 予想 |", "|---|---|:---:|---|"]
    for e in events:
        lines.append(f"| {_when_label(e)} | {_title_label(e)} | {e.importance} | {e.forecast or '—'} |")
    return "\n".join(lines)


def render_summary_list(events: list[ScheduledEvent]) -> str:
    return "\n".join(f"- {_when_label(e)} 【{e.importance}】{_title_label(e)}" for e in events)


def build_calendar(ctx: RunContext) -> SectionContent:
    config = load_events_config()
    events, sources, problems = collect_events(ctx, config)
    window = within_window(events, ctx.now, config.horizon.total_days)
    detail, later = split_by_detail(window, ctx.now, config.horizon.detail_days)
    ctx.data["calendar"] = {"detail": detail, "later": later}

    days = config.horizon
    body = [f"**{days.detail_days}日以内**", ""]
    body.append(render_detail_table(detail) if detail else "予定はありません。")
    body.extend(["", f"**{days.detail_days + 1}〜{days.total_days}日**", ""])
    body.append(render_summary_list(later) if later else "予定はありません。")
    body.extend(["", "時刻は日本時間。時刻のない予定は発表時刻が決まっていないもの。"])
    if problems:
        body.append("")
        body.extend(f"⚠ 取得できませんでした（理由はログを参照）: {p}" for p in problems)

    return SectionContent(
        body="\n".join(body),
        basis=[f"今後の予定: {_window_label(ctx.now, days.total_days)}"],
        sources=sources,
    )


def _window_label(now: datetime, total_days: int) -> str:
    today = now.astimezone(JST).date()
    return f"{format_month_day(today)}〜{format_month_day(today + timedelta(days=total_days))}（取得時点）"
