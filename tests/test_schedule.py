"""今後の予定（events.yaml・FRED・決算）のテスト"""

from datetime import date, datetime

import pytest
from conftest import (
    FRED_FIXTURE,
    YF_EARNINGS_AFTER_FIXTURE,
    YF_EARNINGS_FIXTURE,
    earnings_frame,
    load_fixture_json,
)

from good_morning.collector.fred import parse_release_dates
from good_morning.collector.market_data import earnings_from_raw, fetch_earnings
from good_morning.schedule.config import EventsConfig, load_events_config
from good_morning.schedule.events import (
    EarningsResult,
    ScheduledEvent,
    fred_events,
    next_earnings_event,
    recent_earnings_result,
    split_by_detail,
    static_events,
    to_jst,
    within_window,
)
from good_morning.timeutil import JST

CONFIG = load_events_config()
NOW = datetime(2026, 11, 17, 23, 20, tzinfo=JST)  # 決算の固定データを取った時刻
MORNING = datetime(2026, 11, 18, 7, 15, tzinfo=JST)  # 定時実行の時刻


AFTER = datetime(2026, 11, 18, 11, 15, tzinfo=JST)  # 発表後の固定データを取った時刻


def _earnings(ticker: str, fixture: str = YF_EARNINGS_FIXTURE):
    raw = load_fixture_json(fixture)["earnings"][ticker]
    return earnings_from_raw(ticker, raw["info"], earnings_frame(raw["earnings_dates"]))


# --- events.yaml ----------------------------------------------------------------


def test_shipped_events_config():
    assert (CONFIG.horizon.detail_days, CONFIG.horizon.total_days) == (7, 30)
    titles = [e.title for e in CONFIG.events]
    assert "FOMC 政策金利の発表（12/8〜9会合・経済見通しあり）" in titles
    assert "日銀 金融政策決定会合の結果（12/17〜18会合）" in titles
    # FOMC 議事要旨は公式ページに日付がないものを「推定」にしている
    minutes = [e for e in CONFIG.events if e.category == "fomc_minutes"]
    assert minutes and all(e.estimated for e in minutes)


def test_unknown_category_is_rejected():
    with pytest.raises(ValueError, match="categories"):
        EventsConfig(events=[{"category": "ecb", "date": "2026-12-01", "title": "x"}])


def test_fomc_time_converts_to_jst_with_dst():
    """FOMC の声明 14:00（米東部）は、冬は日本時間 4:00、夏は 3:00（翌日）"""
    assert to_jst(date(2026, 12, 9), "14:00", "America/New_York")[1] == datetime(
        2026, 12, 10, 4, 0, tzinfo=JST
    )
    assert to_jst(date(2027, 6, 9), "14:00", "America/New_York")[1] == datetime(
        2027, 6, 10, 3, 0, tzinfo=JST
    )


def test_static_events_apply_category_defaults():
    events = {e.title: e for e in static_events(CONFIG)}

    fomc = events["FOMC 政策金利の発表（12/8〜9会合・経済見通しあり）"]
    assert (fomc.day, fomc.when.hour, fomc.importance) == (date(2026, 12, 10), 4, "高")
    boj = events["日銀 金融政策決定会合の結果（12/17〜18会合）"]
    assert (boj.day, boj.when, boj.note) == (date(2026, 12, 18), None, "時刻未定・例年は昼ごろ")


# --- FRED -----------------------------------------------------------------------


def test_fred_events_from_real_release_dates():
    """実データ（約900件の発表予定）から、events.yaml に書いた8指標だけを拾う"""
    release_dates = parse_release_dates(load_fixture_json(FRED_FIXTURE))

    events = fred_events(release_dates, CONFIG.fred)
    by_title = {}
    for e in events:
        by_title.setdefault(e.title, []).append(e.day)

    assert len(release_dates) == 900
    assert set(by_title) == {r.title for r in CONFIG.fred.releases}  # 8指標すべて名前が一致
    assert by_title["米雇用統計"] == [date(2026, 12, 4)]
    assert by_title["米個人所得・個人消費支出（PCE）"] == [date(2026, 11, 25)]
    assert len(by_title["米新規失業保険申請件数"]) == 5  # 毎週木曜（感謝祭の週は水曜）
    cpi = next(e for e in events if e.title == "米消費者物価指数（CPI）")
    # 8:30（米東部・冬時間）= 日本時間 22:30
    assert cpi.when == datetime(2026, 12, 10, 22, 30, tzinfo=JST)
    assert cpi.importance == "高"


def test_fred_events_drop_duplicates_and_unknown_releases():
    release_dates = parse_release_dates(
        {
            "release_dates": [
                {"release_id": 18, "release_name": "H.15 Selected Interest Rates", "date": "2026-11-18"},
                {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-12-10"},
                {"release_id": 10, "release_name": "Consumer Price Index", "date": "2026-12-10"},
            ]
        }
    )

    assert [e.title for e in fred_events(release_dates, CONFIG.fred)] == ["米消費者物価指数（CPI）"]


# --- 決算 -----------------------------------------------------------------------


def test_confirmed_earnings_from_info():
    event = next_earnings_event(_earnings("NVDA"), name="エヌビディア", importance="中", now=NOW)

    assert event.when == datetime(2026, 11, 18, 6, 0, tzinfo=JST)  # 16:00（米東部）= 引け後
    assert event.estimated is False
    assert event.forecast == "EPS 2.47ドル"
    assert event.title == "エヌビディア（NVDA）決算"


def test_estimated_earnings_from_info_flag():
    event = next_earnings_event(_earnings("TSM"), name="TSMC", importance="低", now=NOW)

    assert event.day == date(2027, 1, 14)
    assert event.estimated is True
    assert event.forecast == "EPS 5.16ドル"


def test_past_info_falls_back_to_earnings_dates_as_estimate():
    """info の日時が前回の決算（過去）なら、未発表の行から次回を推定する"""
    event = next_earnings_event(_earnings("HOOD"), name="HOOD", importance="低", now=NOW)

    assert event.day == date(2027, 2, 11)
    assert event.estimated is True


def test_earnings_already_reported_is_not_shown():
    """定時実行（11/18 7:15）の時点で NVDA の決算（11/18 6:00）は過去なので出さない"""
    assert next_earnings_event(_earnings("NVDA"), name="x", importance="中", now=MORNING) is None


def test_recent_result_with_reported_eps():
    """発表後（11/18 11:15）の実データ: 実績 2.68・予想 2.47"""
    result = recent_earnings_result(
        _earnings("NVDA", YF_EARNINGS_AFTER_FIXTURE),
        name="エヌビディア", importance="中", now=AFTER, hours=24,
    )

    assert result.when == datetime(2026, 11, 18, 6, 0, tzinfo=JST)
    assert result.name == "エヌビディア（NVDA）"
    assert (result.eps_estimate, result.reported_eps) == (2.47, 2.68)
    assert round(result.surprise_pct, 1) == 8.5


def test_recent_result_before_eps_is_reflected():
    """定時実行（7:15）の時点で取得元に実績がまだない（発表前に取った実データで再現）"""
    result = recent_earnings_result(
        _earnings("NVDA"), name="エヌビディア", importance="中", now=MORNING, hours=24
    )

    assert (result.eps_estimate, result.reported_eps, result.surprise_pct) == (2.47, None, None)


@pytest.mark.parametrize(
    "now,hours",
    [
        (NOW, 24),  # 発表前（23:20）はまだ予定のほう
        (datetime(2026, 11, 19, 6, 0, tzinfo=JST), 24),  # ちょうど24時間後は期間外
        (MORNING, 0),  # 0 なら出さない
    ],
)
def test_recent_result_window(now, hours):
    assert recent_earnings_result(
        _earnings("NVDA", YF_EARNINGS_AFTER_FIXTURE), name="x", importance="中", now=now, hours=hours
    ) is None


def test_recent_result_falls_back_to_confirmed_info_only():
    """行がなくても info の確定した日時が期間内なら出す。推定の日付は使わない"""
    nvda = _earnings("NVDA")
    no_rows = earnings_from_raw(
        "NVDA",
        {"isEarningsDateEstimate": False, "earningsTimestampStart": nvda.next_start.timestamp()},
        None,
    )
    estimated = earnings_from_raw(
        "NVDA",
        {"isEarningsDateEstimate": True, "earningsTimestampStart": nvda.next_start.timestamp()},
        None,
    )

    result = recent_earnings_result(no_rows, name="x", importance="中", now=MORNING, hours=24)
    assert result is not None and result.reported_eps is None
    assert recent_earnings_result(estimated, name="x", importance="中", now=MORNING, hours=24) is None


@pytest.mark.parametrize(
    "estimate,reported,expected",
    [(2.47, 2.68, 8.5), (-0.09, -0.05, 44.4), (1.0, 0.9, -10.0), (0.0, 0.1, None), (None, 0.1, None)],
)
def test_surprise_pct(estimate, reported, expected):
    """予想比は |予想| で割る（赤字予想より良ければプラス）"""
    result = EarningsResult(
        when=MORNING, name="x", importance="中", eps_estimate=estimate, reported_eps=reported
    )
    pct = result.surprise_pct
    assert (None if pct is None else round(pct, 1)) == expected


def test_shipped_recent_hours():
    assert CONFIG.earnings.recent_hours == 24


def test_fetch_earnings_uses_yfinance_boundary(fake_yfinance):
    fake_yfinance(YF_EARNINGS_FIXTURE)

    info = fetch_earnings("AVGO")

    assert info.short_name == "Broadcom Inc."
    assert info.is_estimate is False
    assert info.rows and info.rows[0].eps_estimate is not None


# --- 並べ替えと期間 ---------------------------------------------------------------


def _event(day, hour=None, title="x", importance="中"):
    when = datetime(day.year, day.month, day.day, hour, tzinfo=JST) if hour is not None else None
    return ScheduledEvent(day=day, when=when, title=title, importance=importance, kind="test")


def test_window_drops_past_and_far_events_and_sorts():
    events = [
        _event(date(2026, 11, 17), 22, "過去"),
        _event(date(2026, 11, 18), None, "今日・時刻未定"),
        _event(date(2026, 11, 18), 9, "今日9時"),
        _event(date(2026, 12, 18), 9, "30日目"),
        _event(date(2026, 12, 19), 9, "31日目"),
    ]

    window = within_window(events, MORNING, 30)

    assert [e.title for e in window] == ["今日9時", "今日・時刻未定", "30日目"]


def test_split_by_detail_boundary():
    events = [_event(date(2026, 11, 25), 9, "7日目"), _event(date(2026, 11, 26), 9, "8日目")]

    detail, later = split_by_detail(events, MORNING, 7)

    assert [e.title for e in detail] == ["7日目"]
    assert [e.title for e in later] == ["8日目"]
