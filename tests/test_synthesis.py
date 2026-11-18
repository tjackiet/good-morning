"""今朝のまとめ（Claude）のテスト: 数値の照合・データの組み立て・呼び出し・セクション（Claude には接続しない）"""

import json
from types import SimpleNamespace

import pytest
from conftest import BITBANK_FIXTURE, YF_PRE_OPEN_CAPTURED_AT, YF_PRE_OPEN_FIXTURE

from good_morning.context import RunContext, SectionContent
from good_morning.crypto.builders import build_btc, build_crypto_watchlist
from good_morning.markets.builders import build_markets, build_sectors, build_stock_watchlist
from good_morning.paths import CONFIG_DIR
from good_morning.processor.summarizer import load_prompts
from good_morning.reporter.markdown import STATUS_FAILED, STATUS_OK
from good_morning.sections import SectionSpec, build_sections
from good_morning.synthesis.builders import build_implications, build_summary
from good_morning.synthesis.claude import (
    OUTPUT_SCHEMA,
    Synthesis,
    SynthesisError,
    get_synthesis,
    synthesize,
)
from good_morning.synthesis.facts import build_facts
from good_morning.synthesis.numbers import numbers_in, unknown_numbers
from good_morning.watchlist import load_watchlist

# --- 数値の照合 -------------------------------------------------------------------


def test_numbers_are_normalized():
    """符号・3桁区切り・末尾の0の違いは同じ数値とみなす"""
    assert numbers_in("S&P500 -1.92%、10,350,000円、+3.0bp、04:00") == {
        "500", "1.92", "10350000", "3", "4", "0",
    }  # fmt: skip


def test_unknown_numbers_finds_values_not_in_facts():
    facts = "S&P500: 7,416.59、前日比% -1.92%。VIX 22.91"
    output = "S&P500は1.92%下落し7416.59、VIXは22.91。下落率は約2%で、23億ドルの流出"

    assert unknown_numbers(output, facts) == ["2", "23"]
    assert unknown_numbers("S&P500 -1.92%", facts) == []


# --- データの組み立て ---------------------------------------------------------------


@pytest.fixture
def ctx_with_data(fake_yfinance, fake_bitbank):
    fake_yfinance(YF_PRE_OPEN_FIXTURE)
    fake_bitbank(BITBANK_FIXTURE)
    ctx = RunContext(now=YF_PRE_OPEN_CAPTURED_AT, watchlist=load_watchlist(CONFIG_DIR))
    for builder in (build_markets, build_sectors, build_btc, build_crypto_watchlist, build_stock_watchlist):
        builder(ctx)
    return ctx


def test_facts_use_the_same_notation_as_the_report(ctx_with_data):
    facts = build_facts(ctx_with_data)

    assert "- S&P500（11/16 終値）: 7,416.59、前日比 -145.08、前日比% -1.92%" in facts
    assert "- 米10年債利回り（11/16 終値）: 5.121%、前日比 -3.3bp" in facts  # 利回りは前日比%を出さない
    assert "- ドル円（取得時点）: 159.38" in facts
    assert "日足: 判定 弱気（-4）。雲との位置 雲の下、三役 三役逆転" in facts
    assert "日足 RSI(14) の推移: 11/11 38.5 → 11/12 32.6" in facts
    assert "- XRP/JPY: 155.661円、+2.80%（対BTC +1.51pt）" in facts
    assert "## 今後7日の予定" not in facts  # 作っていないセクションは載せない


def test_facts_without_data_has_no_sections():
    assert "\n## " not in build_facts(RunContext(now=YF_PRE_OPEN_CAPTURED_AT))


# --- Claude の呼び出し（偽のクライアント） ---------------------------------------------

GOOD = {
    "stance": "リスクオフ",
    "summary_lines": [
        "S&P500は-1.92%と下落し、VIXは22.91へ上昇した。",
        "米10年債利回りは5.121%（-3.3bp）。",
        "BTCは日足で弱気（-4）が続く。",
    ],
    "btc_comment": "日足 RSI(14) は 25.6 で売られすぎ。",
    "bullish": ["XRP/JPY は +2.80% と BTC より強い。"],
    "bearish": ["S&P500 は -1.92%。"],
    "conclusion": "様子を見たい。",
}


def _response(payload: dict | str):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    blocks = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=blocks, stop_reason="end_turn")


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def test_synthesize_with_structured_output(ctx_with_data):
    client = FakeClient(_response(GOOD))

    result = synthesize(ctx_with_data, client=client, prompts=load_prompts())

    assert result.stance == "リスクオフ"
    assert result.unverified_numbers == []
    call = client.calls[0]
    assert call["output_config"] == {"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}}
    assert call["model"] == "claude-sonnet-5"
    assert "7,416.59" in call["messages"][0]["content"]  # 計算済みの数値を渡している


def test_unknown_numbers_trigger_one_retry(ctx_with_data):
    bad = {**GOOD, "summary_lines": ["S&P500は約12.34%下落した。", *GOOD["summary_lines"][1:]]}
    client = FakeClient(_response(bad), _response(GOOD))

    result = synthesize(ctx_with_data, client=client, prompts=load_prompts())

    assert len(client.calls) == 2
    feedback = client.calls[1]["messages"][-1]["content"]
    assert "次の数値は渡したデータにありません: 12.34" in feedback
    assert result.summary_lines[0].startswith("S&P500は-1.92%")
    assert result.unverified_numbers == []


def test_numbers_still_unknown_after_retry_are_reported(ctx_with_data):
    bad = {**GOOD, "conclusion": "5万ドル台を試す可能性も。23億ドルの流出。"}
    client = FakeClient(_response(bad), _response(bad))

    result = synthesize(ctx_with_data, client=client, prompts=load_prompts())

    # "5" は「5要素」としてデータにあるため照合では見つけられない（照合の限界）。"23" は見つかる
    assert result.unverified_numbers == ["23"]
    body = build_summary_from(result)
    assert "⚠ 次の数値は元データで確認できませんでした: 23" in body


def build_summary_from(result: Synthesis) -> str:
    ctx = RunContext(now=YF_PRE_OPEN_CAPTURED_AT, data={"_synthesis": result})
    return build_summary(ctx).body


def test_invalid_output_raises(ctx_with_data):
    client = FakeClient(_response('{"stance": "強気"}'))

    with pytest.raises(SynthesisError):
        synthesize(ctx_with_data, client=client, prompts=load_prompts())


def test_extra_summary_lines_are_trimmed(ctx_with_data):
    many = {**GOOD, "summary_lines": [*GOOD["summary_lines"], "S&P500 -1.92%。"]}

    result = synthesize(ctx_with_data, client=FakeClient(_response(many)), prompts=load_prompts())

    assert len(result.summary_lines) == 3


def test_no_data_means_no_call():
    with pytest.raises(SynthesisError, match="材料"):
        synthesize(RunContext(now=YF_PRE_OPEN_CAPTURED_AT), client=FakeClient())


def test_get_synthesis_calls_once_even_on_failure(monkeypatch):
    calls = []

    def failing(ctx):
        calls.append(1)
        raise SynthesisError("boom")

    monkeypatch.setattr("good_morning.synthesis.claude.synthesize", failing)
    ctx = RunContext(now=YF_PRE_OPEN_CAPTURED_AT)

    for _ in range(2):
        with pytest.raises(SynthesisError):
            get_synthesis(ctx)
    assert len(calls) == 1


# --- セクション ------------------------------------------------------------------------


def _ctx_with(result: Synthesis) -> RunContext:
    return RunContext(now=YF_PRE_OPEN_CAPTURED_AT, data={"_synthesis": result})


def test_summary_and_implications_render():
    s = Synthesis(**GOOD)

    summary = build_summary(_ctx_with(s)).body
    implications = build_implications(_ctx_with(s)).body

    assert summary.startswith("**判定: 🔴 リスクオフ**")
    assert "1. S&P500は-1.92%と下落し" in summary and "3. BTCは日足で弱気" in summary
    assert "元データと機械的に照合済み" in summary
    assert "**強気材料**\n\n- XRP/JPY は +2.80% と BTC より強い。" in implications
    assert implications.endswith("**まとめ**: 様子を見たい。")


def test_synthesis_sections_are_built_after_data_and_btc_gets_comment():
    order = []

    def data_builder(ctx):
        order.append("btc")
        return SectionContent(body="BTC の表")

    def summary_builder(ctx):
        order.append("summary")
        ctx.data["synthesis"] = Synthesis(**GOOD)
        return SectionContent(body="まとめ")

    specs = [
        SectionSpec("summary", "今朝のまとめ", 5, summary_builder, stage="synthesis"),
        SectionSpec("btc", "BTCの詳細", 2, data_builder),
    ]
    sections = build_sections(RunContext(now=YF_PRE_OPEN_CAPTURED_AT), specs)

    assert order == ["btc", "summary"]  # 表示は summary が先でも、作るのはデータが先
    assert [s.key for s in sections] == ["summary", "btc"]
    assert sections[1].body.endswith("**まとめ（Claude）**: 日足 RSI(14) は 25.6 で売られすぎ。")


def test_synthesis_failure_marks_both_sections_failed(monkeypatch):
    monkeypatch.setattr(
        "good_morning.synthesis.claude.synthesize",
        lambda ctx: (_ for _ in ()).throw(SynthesisError("no key")),
    )
    specs = [
        SectionSpec("summary", "今朝のまとめ", 5, build_summary, stage="synthesis"),
        SectionSpec("crypto_implications", "暗号資産への示唆", 5, build_implications, stage="synthesis"),
    ]

    sections = build_sections(RunContext(now=YF_PRE_OPEN_CAPTURED_AT), specs)

    assert [s.status for s in sections] == [STATUS_FAILED, STATUS_FAILED]
    assert STATUS_OK not in [s.status for s in sections]
