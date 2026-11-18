"""「今後の予定」セクションのテスト（決算・FRED とも実データの fixtures）"""

import pytest
from conftest import FRED_FIXTURE, YF_EARNINGS_FIXTURE, load_fixture_json
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


def test_morning_run_drops_reported_earnings(fake_yfinance, fake_fred):
    fake_yfinance(YF_EARNINGS_FIXTURE)
    fake_fred()

    content = build_calendar(_ctx(MORNING))

    assert "エヌビディア" not in content.body
    assert content.basis == ["今後の予定: 11/18（水）〜12/18（金）（取得時点）"]
    assert "- 12/18（金） 【高】日銀 金融政策決定会合の結果（12/17〜18会合）（時刻未定・例年は昼ごろ）" in content.body
    assert MORNING.tzinfo is JST
