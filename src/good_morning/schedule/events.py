"""今後の予定の組み立て（events.yaml・FRED・決算を ScheduledEvent にそろえる。純粋な処理）"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from good_morning.collector.fred import ReleaseDate
from good_morning.collector.market_data import EarningsInfo
from good_morning.schedule.config import EventsConfig, FredConfig, Importance
from good_morning.timeutil import JST

IMPORTANCE_ORDER = {"高": 0, "中": 1, "低": 2}


@dataclass(frozen=True)
class ScheduledEvent:
    day: date  # 日本時間の日付
    when: datetime | None  # 日本時間の日時（時刻が分からなければ None）
    title: str
    importance: Importance
    kind: str  # fomc / fomc_minutes / boj / indicator / earnings など
    forecast: str | None = None  # 予想値（取れたときだけ）
    estimated: bool = False  # 日付が推定
    note: str | None = None

    @property
    def sort_key(self) -> tuple:
        # 時刻未定の予定はその日の最後に並べる
        moment = self.when or datetime.combine(self.day, time(23, 59, 59), tzinfo=JST)
        return (moment, IMPORTANCE_ORDER[self.importance], self.title)


def _parse_time(text: str) -> time:
    hour, minute = (int(part) for part in text.split(":"))
    return time(hour, minute)


def to_jst(day: date, clock: str | None, timezone: str) -> tuple[date, datetime | None]:
    """現地の日付と時刻を日本時間にする。時刻がなければ日付だけ（現地の日付のまま）"""
    if not clock:
        return day, None
    local = datetime.combine(day, _parse_time(clock), tzinfo=ZoneInfo(timezone))
    jst = local.astimezone(JST)
    return jst.date(), jst


def static_events(config: EventsConfig) -> list[ScheduledEvent]:
    events = []
    for e in config.events:
        defaults = config.categories[e.category]
        day, when = to_jst(e.date, e.time or defaults.time, e.timezone or defaults.timezone)
        events.append(
            ScheduledEvent(
                day=day,
                when=when,
                title=e.title,
                importance=e.importance or defaults.importance,
                kind=e.category,
                estimated=e.estimated,
                note=e.note or (defaults.note if not (e.time or defaults.time) else None),
            )
        )
    return events


def fred_events(release_dates: list[ReleaseDate], config: FredConfig) -> list[ScheduledEvent]:
    """FRED の発表予定日のうち、events.yaml に書いた指標だけを予定にする"""
    wanted = {r.name: r for r in config.releases}
    events, seen = [], set()
    for rd in release_dates:
        release = wanted.get(rd.release_name)
        if release is None or (rd.release_name, rd.date) in seen:
            continue
        seen.add((rd.release_name, rd.date))
        day, when = to_jst(rd.date, release.time, config.timezone)
        events.append(
            ScheduledEvent(
                day=day, when=when, title=release.title, importance=release.importance, kind="indicator"
            )
        )
    return events


def next_earnings_event(
    earnings: EarningsInfo, *, name: str, importance: Importance, now: datetime
) -> ScheduledEvent | None:
    """次回の決算を1件返す（今より後のものだけ。なければ None）

    info の次回の日時が今より後ならそれを使い、確定か推定かは isEarningsDateEstimate に従う。
    info の日時が過去（前回の決算）なら、get_earnings_dates() の未発表の行から次回を推定する。
    """
    when, end, estimated = None, None, True
    if earnings.next_start is not None and earnings.next_start > now:
        when, end = earnings.next_start, earnings.next_end
        estimated = earnings.is_estimate is not False
    else:
        upcoming = [r for r in earnings.rows if r.when > now and r.reported_eps is None]
        if upcoming:
            when = min(upcoming, key=lambda r: r.when).when
    if when is None:
        return None

    # EPS 予想は get_earnings_dates() の、日付が近い（前後2日以内の）行から取る
    eps = None
    for row in earnings.rows:
        if abs(row.when - when) <= timedelta(days=2) and row.eps_estimate is not None:
            eps = row.eps_estimate
            break

    when_jst = when.astimezone(JST)
    note = None
    if end is not None and end.astimezone(JST).date() != when_jst.date():
        note = f"{when_jst:%m/%d}〜{end.astimezone(JST):%m/%d} のいずれか"
    return ScheduledEvent(
        day=when_jst.date(),
        when=when_jst,
        title=f"{name}（{earnings.ticker}）決算",
        importance=importance,
        kind="earnings",
        forecast=f"EPS {eps:.2f}ドル" if eps is not None else None,
        estimated=estimated,
        note=note,
    )


def within_window(
    events: list[ScheduledEvent], now: datetime, total_days: int
) -> list[ScheduledEvent]:
    """今より後で、今日から total_days 日以内の予定を日時順に返す"""
    today = now.astimezone(JST).date()
    last_day = today + timedelta(days=total_days)
    kept = []
    for e in events:
        if e.day < today or e.day > last_day:
            continue
        if e.when is not None and e.when <= now:
            continue
        kept.append(e)
    return sorted(kept, key=lambda e: e.sort_key)


def split_by_detail(
    events: list[ScheduledEvent], now: datetime, detail_days: int
) -> tuple[list[ScheduledEvent], list[ScheduledEvent]]:
    """(今日から detail_days 日以内, それより先) に分ける"""
    cutoff = now.astimezone(JST).date() + timedelta(days=detail_days)
    return [e for e in events if e.day <= cutoff], [e for e in events if e.day > cutoff]
