"""「今後の予定」セクションのテスト（決算・FRED とも実データの fixtures）"""

import pytest
from conftest import FRED_FIXTURE, YF_EARNINGS_AFTER_FIXTURE, YF_EARNINGS_FIXTURE, load_fixture_json
from test_schedule import MORNING, NOW

from good_morning.collector.fred import FredError, parse_release_dates
from good_morning.context import RunContext
from good_morning.paths import CONFIG_DIR
from good_morning.schedule.builder import build_calendar
from good_morning.timeutil import JST
from good_morning.watchlist import load_watchlist


@pytest.fixture
def fake_fred(monkeypatch):
    def _install(error: Exception | None = None):
        def _fetch(start, end, api_key=None):
            if error:
                raise error
            rows = parse_release_dates(load_fixture_json(FRED_FIXTURE))
            return [r for r in rows if start <= r.date <= end]

        monkeypatch.setattr("good_morning.collector.fred.fetch_release_dates", _fetch)

    return _install


def _ctx(now=NOW):
    return RunContext(now=now, watchlist=load_watchlist(CONFIG_DIR))


def test_calendar_section(fake_yfinance, fake_fred):
    fake_yfinance(YF_EARNINGS_FIXTURE)
    fake_fred()

    content = build_calendar(_ctx())
    body = content.body
    detail, later = body.split("**8〜30日**")

    # 7日以内: 決算（確定・EPS 予想あり）、FOMC 議事要旨（推定）、FRED の指標
    assert "| 11/18（水） 06:00 | エヌビディア（NVDA）決算 | 中 | EPS 2.47ドル |" in detail
    assert "FOMC 議事要旨（10/27〜28会合）（日付は推定）" in detail
    assert "| 11/19（木） 22:30 | 米新規失業保険申請件数 | 低 | — |" in detail
    assert "米個人所得・個人消費支出（PCE）" in later  # 11/25 は8日目（7日以内は 11/24 まで）
    # 8〜30日: FOMC（日本時間 12/10 4:00）、Broadcom の決算（related は会社名）、CPI
    assert "- 12/10（木） 04:00 【高】FOMC 政策金利の発表（12/8〜9会合・経済見通しあり）" in later
    assert "【低】Broadcom Inc.（AVGO）決算" in later
    assert "【高】米消費者物価指数（CPI）" in later
    assert "⚠" not in body
    assert "FRED（セントルイス連銀）" in content.sources
    # 日時順に並ぶ
    assert detail.index("エヌビディア") < detail.index("FOMC 議事要旨") < detail.index("米新規失業")


def test_fred_failure_keeps_other_sources(fake_yfinance, fake_fred, caplog):
    fake_yfinance(YF_EARNINGS_FIXTURE)
    fake_fred(FredError("環境変数 FRED_API_KEY が設定されていません"))

    content = build_calendar(_ctx())

    assert "エヌビディア（NVDA）決算" in content.body
    assert "⚠ 取得できませんでした（理由はログを参照）: 米経済指標（FRED）" in content.body
    assert "FRED（セントルイス連銀）" not in content.sources
    assert "FRED_API_KEY" in caplog.text


def test_earnings_failures_are_listed(fake_yfinance, fake_fred):
    fake_yfinance({"earnings": {}})  # どの銘柄も取れない
    fake_fred()

    content = build_calendar(_ctx())

    assert "⚠ 取得できませんでした（理由はログを参照）: 決算日: NVDA, COIN, MSTR, TSM" in content.body
    assert "FOMC 議事要旨" in content.body


def test_morning_run_moves_passed_earnings_to_results(fake_yfinance, fake_fred):
    """定時実行（7:15）: 6:00 の NVDA の決算は予定から消え、直近の決算に出る（実績はまだ取得元にない）"""
    fake_yfinance(YF_EARNINGS_FIXTURE)
    fake_fred()
    ctx = _ctx(MORNING)

    content = build_calendar(ctx)
    results, upcoming = content.body.split("**7日以内**")

    assert results.startswith("**直近の決算（過去24時間）**")
    assert "| 11/18（水） 06:00 | エヌビディア（NVDA） | 未反映 | 2.47ドル | — |" in results
    assert "「未反映」は、発表予定の時刻を過ぎたが取得元に実績がまだないもの。" in results
    assert "エヌビディア" not in upcoming
    assert len(ctx.data["calendar"]["recent"]) == 1
    assert content.basis == ["今後の予定: 11/18（水）〜12/18（金）（取得時点）"]
    assert "- 12/18（金） 【高】日銀 金融政策決定会合の結果（12/17〜18会合）（時刻未定・例年は昼ごろ）" in content.body
    assert MORNING.tzinfo is JST


def test_results_after_eps_is_reflected(fake_yfinance, fake_fred):
    """発表後（11/18 11:15）の実データ: 実績・予想・予想比がそろう"""
    from datetime import datetime

    fake_yfinance(YF_EARNINGS_AFTER_FIXTURE)
    fake_fred()

    content = build_calendar(_ctx(datetime(2026, 11, 18, 11, 15, tzinfo=JST)))

    assert "| 11/18（水） 06:00 | エヌビディア（NVDA） | 2.68ドル | 2.47ドル | +8.5% |" in content.body
    assert "未反映" not in content.body
    assert "EPS（1株利益）は Yahoo Finance の値" in content.body


def test_no_results_section_without_recent_earnings(fake_yfinance, fake_fred):
    fake_yfinance(YF_EARNINGS_FIXTURE)
    fake_fred()

    content = build_calendar(_ctx())  # 11/17 23:20（発表前）

    assert content.body.startswith("**7日以内**")


def test_recent_results_flow_into_facts_view_and_card(fake_yfinance, fake_fred):
    """直近の決算は、Claude に渡すデータ・ビジュアルレポート・画像のカードにも載る"""
    from datetime import datetime

    from good_morning.reporter.markdown import STATUS_OK, ReportMeta, Section
    from good_morning.synthesis.facts import build_facts
    from good_morning.visual.card import render_card_html
    from good_morning.visual.render import render_html
    from good_morning.visual.viewmodel import build_view

    after = datetime(2026, 11, 18, 11, 15, tzinfo=JST)
    fake_yfinance(YF_EARNINGS_AFTER_FIXTURE)
    fake_fred()
    ctx = _ctx(after)
    content = build_calendar(ctx)

    facts = build_facts(ctx)
    assert "## 直近の決算（過去24時間。EPS は1株利益）" in facts
    assert "- 11/18（水） 06:00 エヌビディア（NVDA）: EPS 実績 2.68ドル・予想 2.47ドル・予想比 +8.5%" in facts

    section = Section(
        key="calendar", title="今後の予定", status=STATUS_OK, basis=content.basis, sources=content.sources
    )
    view = build_view(ctx, [section], ReportMeta(generated_at=after))
    assert view["calendar"]["recent"] == [
        {
            "when": "11/18（水） 06:00",
            "name": "エヌビディア（NVDA）",
            "importance": "中",
            "reported_label": "2.68ドル",
            "estimate_label": "2.47ドル",
            "surprise_label": "+8.5%",
            "direction": 1,
        }
    ]
    html = render_html(view)
    assert "直近の決算<span class=\"sub\">過去24時間" in html
    assert "▲ 予想比 +8.5%" in html and "未反映" not in html
    card = render_card_html(view)
    assert "<b>エヌビディア（NVDA）</b> 2.68ドル<span class=\"nowrap\">（予想比" in card


def test_unreflected_result_in_facts_and_card(fake_yfinance, fake_fred):
    from good_morning.reporter.markdown import STATUS_OK, ReportMeta, Section
    from good_morning.synthesis.facts import build_facts
    from good_morning.visual.card import render_card_html
    from good_morning.visual.render import render_html
    from good_morning.visual.viewmodel import build_view

    fake_yfinance(YF_EARNINGS_FIXTURE)
    fake_fred()
    ctx = _ctx(MORNING)
    content = build_calendar(ctx)

    assert "- 11/18（水） 06:00 エヌビディア（NVDA）: EPS の実績は取得元に未反映、EPS 予想 2.47ドル" in build_facts(ctx)
    section = Section(key="calendar", title="今後の予定", status=STATUS_OK, basis=content.basis)
    view = build_view(ctx, [section], ReportMeta(generated_at=MORNING))
    assert "実績 <b class=\"num\">未反映</b>" in render_html(view)
    assert "「未反映」は、発表予定の時刻を過ぎたが" in render_html(view)
    assert "<b>エヌビディア（NVDA）</b> 実績は未反映" in render_card_html(view)
