"""「今後の予定」のセクション

3つの取得元（events.yaml・FRED・決算）は独立して扱い、どれかが失敗しても
残りで表を作る。失敗した取得元はセクションの末尾に「取得できなかった」と書き、理由はログに残す。
"""

import logging
from datetime import datetime, timedelta
from typing import NamedTuple

from good_morning.collector import fred, market_data
from good_morning.context import RunContext, SectionContent
from good_morning.schedule.config import EventsConfig, load_events_config
from good_morning.schedule.events import (
    EarningsResult,
    ScheduledEvent,
    fred_events,
    next_earnings_event,
    recent_earnings_result,
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


class Collected(NamedTuple):
    events: list[ScheduledEvent]  # 今後の予定（期間で絞る前）
    results: list[EarningsResult]  # 直近の決算（発表予定の時刻を過ぎたもの）
    sources: list[str]  # 使えた取得元
    problems: list[str]  # 取得できなかったものの説明


def collect_events(ctx: RunContext, config: EventsConfig) -> Collected:
    events: list[ScheduledEvent] = []
    results: list[EarningsResult] = []
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
            result = recent_earnings_result(
                info,
                name=display,
                importance=importance,
                now=ctx.now,
                hours=config.earnings.recent_hours,
            )
            if result is not None:
                results.append(result)
        except Exception as e:  # noqa: BLE001 - 1銘柄の失敗で止めない
            logger.warning("今後の予定（決算 %s）: 取得失敗 - %s", ticker, e)
            failed_tickers.append(ticker)
    if targets and len(failed_tickers) < len(targets):
        sources.append(SOURCE_EARNINGS)
    if failed_tickers:
        problems.append(f"決算日: {', '.join(failed_tickers)}")

    results.sort(key=lambda r: (r.when, r.name))
    return Collected(events, results, sources, problems)


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


def eps_label(value: float | None) -> str | None:
    return None if value is None else f"{value:.2f}ドル"


def surprise_label(result: EarningsResult) -> str | None:
    pct = result.surprise_pct
    return None if pct is None else f"{pct:+.1f}%"


def render_results_table(results: list[EarningsResult]) -> str:
    lines = [
        "| 発表予定（日本時間） | 企業 | EPS 実績 | EPS 予想 | 予想比 |",
        "|---|---|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {format_month_day(r.when.date())} {r.when:%H:%M} | {r.name} "
            f"| {eps_label(r.reported_eps) or '未反映'} | {eps_label(r.eps_estimate) or '—'} "
            f"| {surprise_label(r) or '—'} |"
        )
    return "\n".join(lines)


def results_note(results: list[EarningsResult]) -> str:
    note = "EPS（1株利益）は Yahoo Finance の値（会社の発表とは調整のしかたが違うことがある）。時刻は取得元の目安。"
    if any(r.reported_eps is None for r in results):
        note += "「未反映」は、発表予定の時刻を過ぎたが取得元に実績がまだないもの。"
    return note


def build_calendar(ctx: RunContext) -> SectionContent:
    config = load_events_config()
    events, results, sources, problems = collect_events(ctx, config)
    window = within_window(events, ctx.now, config.horizon.total_days)
    detail, later = split_by_detail(window, ctx.now, config.horizon.detail_days)
    ctx.data["calendar"] = {
        "detail": detail,
        "later": later,
        "recent": results,
        "recent_hours": config.earnings.recent_hours,
    }

    days = config.horizon
    body: list[str] = []
    if results:
        body.extend(
            [
                f"**直近の決算（過去{config.earnings.recent_hours}時間）**",
                "",
                render_results_table(results),
                "",
                results_note(results),
                "",
            ]
        )
    body.extend([f"**{days.detail_days}日以内**", ""])
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
