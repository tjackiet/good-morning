"""BTC 現物ETF の資金流出入（SoSoValue）のテスト（ネットワークなし）"""

from datetime import date, datetime

import httpx
import pytest
from conftest import ETF_FIXTURE, JST, load_fixture_json

from good_morning.collector import sosovalue
from good_morning.collector.sosovalue import (
    SoSoValueError,
    parse_fund_history,
    parse_summary,
    unwrap,
)
from good_morning.context import RunContext
from good_morning.etf.builder import (
    assemble,
    billions_label,
    build_btc_etf,
    flow_label,
    render_body,
)
from good_morning.etf.config import EtfConfig, load_etf_config
from good_morning.reporter.markdown import STATUS_OK, ReportMeta, Section
from good_morning.synthesis.facts import build_facts

NOW = datetime(2026, 11, 20, 9, 30, tzinfo=JST)


def _data():
    return load_fixture_json(ETF_FIXTURE)


def _assemble(summary=True, funds=None):
    data = _data()
    parsed = {t: parse_fund_history(p) for t, p in data["funds"].items()}
    parsed.update(funds or {})
    return assemble(parse_summary(data["summary"]) if summary else None, parsed, load_etf_config())


# --- 取得（応答の読み取り） ---------------------------------------------------------


def test_shipped_config():
    config = load_etf_config()
    assert [f.ticker for f in config.funds] == ["IBIT", "FBTC", "GBTC", "ARKB", "BITB"]
    assert (config.symbol, config.country_code, config.recent_days) == ("BTC", "US", 5)


def test_fund_ticker_must_be_safe_for_url_path():
    with pytest.raises(ValueError):
        EtfConfig(funds=[{"ticker": "../x", "issuer": "x"}])


def test_parse_real_summary_latest_first():
    days = parse_summary(_data()["summary"])

    assert days[0].date == date(2026, 11, 18)
    assert days[0].net_inflow == pytest.approx(-306421294.335)
    assert days[1].net_inflow == pytest.approx(-239944866.82)  # Farside の 11/17 は -239m
    assert all(d.settled for d in days)


def test_unsettled_row_has_no_flow_values():
    """IBIT の 11/19 の行は、流入などの項目がない（確定前）"""
    ibit = parse_fund_history(_data()["funds"]["IBIT"])

    assert (ibit[0].date, ibit[0].settled, ibit[0].net_inflow) == (date(2026, 11, 19), False, None)
    assert ibit[1].date == date(2026, 11, 18) and ibit[1].net_inflow == -148663200


def test_unwrap_accepts_bare_list_and_rejects_error_codes():
    assert unwrap([{"date": "2026-11-18"}]) == [{"date": "2026-11-18"}]
    with pytest.raises(SoSoValueError, match="400101"):
        unwrap({"code": 400101, "message": "API Key is invalid or does not exist"})
    with pytest.raises(SoSoValueError):
        unwrap({"unexpected": True})


class _Response:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_get_sends_key_in_header(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return _Response(200, _data()["summary"])

    monkeypatch.setattr("httpx.get", fake_get)
    days = sosovalue.fetch_summary_history(api_key="secret-key")

    assert seen["url"] == "https://openapi.sosovalue.com/openapi/v1/etfs/summary-history"
    assert seen["headers"]["x-soso-api-key"] == "secret-key"
    assert "secret-key" not in seen["url"] and "secret-key" not in str(seen["params"])
    assert len(days) == 10


def test_errors_never_include_the_api_key(monkeypatch):
    monkeypatch.setattr(
        "httpx.get", lambda *a, **k: _Response(401, {"code": 400101, "message": "key secret-key bad"})
    )
    with pytest.raises(SoSoValueError) as e:
        sosovalue.fetch_fund_history("IBIT", api_key="secret-key")
    assert "HTTP 401" in str(e.value) and "400101" in str(e.value)
    assert "secret-key" not in str(e.value)

    def broken(*a, **k):
        raise httpx.ConnectError("https://openapi.sosovalue.com secret-key")

    monkeypatch.setattr("httpx.get", broken)
    with pytest.raises(SoSoValueError) as e:
        sosovalue.fetch_fund_history("IBIT", api_key="secret-key")
    assert "ConnectError" in str(e.value) and "secret-key" not in str(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("SOSO_API_KEY", raising=False)
    with pytest.raises(SoSoValueError, match="SOSO_API_KEY"):
        sosovalue.get_api_key()


# --- 表の組み立て --------------------------------------------------------------------


def test_dates_are_aligned_to_the_latest_settled_total():
    """GBTC などは 11/19 まで確定していても、合計の最新の確定日（11/18）にそろえる"""
    flows = _assemble()

    assert flows.basis_date == date(2026, 11, 18)
    assert [d.date.day for d in flows.recent] == [12, 13, 16, 17, 18]  # 古い順・5営業日
    assert [f.day.date for f in flows.funds] == [date(2026, 11, 18)] * 5
    assert [flow_label(f.day.net_inflow) for f in flows.funds] == [
        "-148.7", "-69.3", "-20.3", "-19.3", "-36.6",
    ]  # fmt: skip


def test_without_total_uses_the_day_all_funds_settled():
    flows = _assemble(summary=False)

    assert flows.basis_date == date(2026, 11, 18)  # IBIT・FBTC が 11/18 まで
    assert flows.recent == [] and flows.total is None and flows.summary_failed


def test_failed_fund_is_marked_and_others_remain():
    flows = _assemble(funds={"FBTC": None})
    body = render_body(flows, ["FBTC"])

    assert "| FBTC | フィデリティ | 取得失敗 | — | — |" in body
    assert "| IBIT | ブラックロック | -148.7 | 未確定 | 487 |" in body
    assert "未確定: IBIT）" in body  # 取得に失敗した FBTC は「未確定」に数えない
    assert "⚠ 取得できませんでした（理由はログを参照）: FBTC" in body


def test_unsettled_fund_on_basis_date_is_shown_as_pending():
    data = _data()
    ibit = [d for d in parse_fund_history(data["funds"]["IBIT"]) if d.date != date(2026, 11, 18)]
    body = render_body(_assemble(funds={"IBIT": ibit}), [])

    assert "| IBIT | ブラックロック | 未確定 | 未確定 | — |" in body


def test_render_body_matches_report_notation():
    body = render_body(_assemble(), [])

    assert "| 11/17（火） | -239.9 |" in body
    assert "| 11/18（水） | -306.4 |" in body
    assert "累計の純流入 +541億ドル・純資産 777億ドル（11/18 時点）" in body
    assert "**銘柄別の純流入（百万ドル）**" in body
    assert "| 銘柄 | 運用会社 | 11/18 | 11/19（一部） | 純資産（億ドル・11/18） |" in body
    assert "| GBTC | グレースケール | -20.3 | -13.9 | 76 |" in body
    assert "| BITB | ビットワイズ | -36.6 | 0.0 | 23 |" in body
    assert "11/19 は確定した銘柄だけ（合計はまだ出ていない。未確定: IBIT・FBTC）" in body
    assert "翌営業日に確定" in body


def test_newer_days_settled_for_some_funds_are_kept():
    """そろえた日（11/18）より新しい 11/19 に確定している GBTC・ARKB・BITB の分を捨てない"""
    flows = _assemble()

    assert flows.newer_dates == [date(2026, 11, 19)]
    newer = {f.ticker: f.newer.get(date(2026, 11, 19)) for f in flows.funds}
    assert newer["IBIT"] is None and newer["FBTC"] is None
    assert [flow_label(newer[t].net_inflow) for t in ("GBTC", "ARKB", "BITB")] == ["-13.9", "-31.3", "0.0"]


def test_no_newer_column_when_all_funds_are_aligned():
    data = _data()
    trimmed = {
        t: [d for d in parse_fund_history(p) if d.date <= date(2026, 11, 18)] for t, p in data["funds"].items()
    }
    flows = _assemble(funds=trimmed)
    body = render_body(flows, [])

    assert flows.newer_dates == []
    assert "| 銘柄 | 運用会社 | 11/18 | 純資産（億ドル・11/18） |" in body
    assert "（一部）" not in body


@pytest.mark.parametrize(
    "usd,expected",
    [(-306421294.335, "-306.4"), (7986219.7, "+8.0"), (0, "0.0"), (-40000, "0.0"), (1234567890, "+1,234.6")],
)
def test_flow_label(usd, expected):
    assert flow_label(usd) == expected


def test_billions_label():
    assert billions_label(77706592903.47) == "777"
    assert billions_label(54094730907.23, signed=True) == "+541"


# --- セクション・Claude に渡すデータ・ビジュアル・通知 ------------------------------------


def test_build_section_with_fixture(fake_sosovalue):
    calls = fake_sosovalue()
    ctx = RunContext(now=NOW)

    content = build_btc_etf(ctx)

    assert calls == ["summary", "IBIT", "FBTC", "GBTC", "ARKB", "BITB"]
    assert content.basis == ["BTC 現物ETF の資金流出入: 11/18（水） の確定値（米国の取引日ごと。翌営業日に確定）"]
    assert content.sources == ["SoSoValue（BTC 現物ETF の資金流出入）"]
    assert ctx.data["btc_etf"].basis_date == date(2026, 11, 18)


def test_summary_failure_keeps_funds(fake_sosovalue):
    fake_sosovalue(failing=("summary",))
    content = build_btc_etf(RunContext(now=NOW))

    assert "**合計（米国の BTC 現物ETF）**\n\n取得失敗" in content.body
    assert "| IBIT | ブラックロック | -148.7 | 未確定 | 487 |" in content.body
    assert "⚠ 取得できませんでした（理由はログを参照）: 合計" in content.body


def test_everything_failing_raises(fake_sosovalue):
    fake_sosovalue(failing=("summary", "IBIT", "FBTC", "GBTC", "ARKB", "BITB"))
    with pytest.raises(SoSoValueError):
        build_btc_etf(RunContext(now=NOW))


def test_missing_key_fails_the_section(fake_sosovalue, monkeypatch):
    fake_sosovalue()
    monkeypatch.delenv("SOSO_API_KEY")
    with pytest.raises(SoSoValueError, match="SOSO_API_KEY"):
        build_btc_etf(RunContext(now=NOW))


def test_flows_reach_facts_view_html_and_notification(fake_sosovalue):
    from good_morning.notify.message import build_notification
    from good_morning.visual.render import render_html
    from good_morning.visual.viewmodel import build_view

    fake_sosovalue()
    ctx = RunContext(now=NOW)
    content = build_btc_etf(ctx)

    facts = build_facts(ctx)
    assert "## BTC 現物ETF の資金流出入（米国。11/18 までの確定値" in facts
    assert "- 合計の純流入（古い順）: 11/12（木） -284.0、" in facts and "11/18（水） -306.4" in facts
    assert "- 銘柄別の純流入（11/18）: IBIT（ブラックロック）-148.7、FBTC（フィデリティ）-69.3" in facts
    assert (
        "- 銘柄別の純流入（11/19。一部の銘柄だけ確定していて、合計はまだ出ていない）: "
        "GBTC（グレースケール）-13.9、ARKB（アーク・21シェアーズ）-31.3、BITB（ビットワイズ）0.0。未確定: IBIT・FBTC"
    ) in facts

    section = Section(key="btc_etf", title="BTC 現物ETF の資金流出入", status=STATUS_OK, basis=content.basis)
    view = build_view(ctx, [section], ReportMeta(generated_at=NOW))
    etf = view["etf"]
    assert (etf["date"], etf["date_short"], etf["total"]) == (
        "11/18（水）", "11/18", {"label": "-306.4", "value": -306.4},
    )  # fmt: skip
    assert etf["funds"][0] == {
        "ticker": "IBIT", "issuer": "ブラックロック", "value_label": "-148.7", "value": -148.7, "failed": False,
    }  # fmt: skip

    assert etf["newer"] == [
        {
            "date": "11/19（木）",
            "funds": [
                {"ticker": "GBTC", "value_label": "-13.9", "value": -13.9},
                {"ticker": "ARKB", "value_label": "-31.3", "value": -31.3},
                {"ticker": "BITB", "value_label": "0.0", "value": 0.0},
            ],
            "pending": ["IBIT", "FBTC"],
        }
    ]

    html = render_html(view)
    assert '<h2 id="h-etf">BTC 現物ETF の資金流出入' in html
    assert '<svg class="flow"' in html and "<title>11/18（水） -306.4百万ドル</title>" in html
    assert "11/19（木）・確定した銘柄だけ" in html
    assert "（未確定: IBIT・FBTC。合計もまだ出ていない）" in html
    assert "▼ -306.4</span><span class=\"unit\">百万ドル" in html
    assert "累計の純流入 +541億ドル・純資産 777億ドル（11/18 時点）" in html

    message = build_notification(view, "https://claude.ai/artifact/x", "outputs/x.md")
    assert "BTC 現物ETF の純流入（11/18）: -306.4百万ドル" in message
