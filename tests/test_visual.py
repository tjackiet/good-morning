"""ビジュアルレポート（ビューモデル・グラフの部品・HTML）のテスト（ネットワークなし）"""

import json

import pytest
from conftest import BITBANK_FIXTURE, YF_PRE_OPEN_CAPTURED_AT, YF_PRE_OPEN_FIXTURE

from good_morning.context import RunContext
from good_morning.crypto.builders import build_btc, build_crypto_watchlist
from good_morning.markets.builders import build_markets, build_sectors, build_stock_watchlist
from good_morning.paths import CONFIG_DIR
from good_morning.reporter.markdown import STATUS_FAILED, STATUS_OK, ReportMeta, Section
from good_morning.synthesis.claude import Synthesis
from good_morning.visual.charts import add_bar_widths, rsi_domain, rsi_svg
from good_morning.visual.render import load_view, render_html, safe_url, save_view, upgrade_view
from good_morning.visual.viewmodel import build_view, split_label
from good_morning.watchlist import load_watchlist

SYNTHESIS = Synthesis(
    stance="リスクオフ",
    summary_lines=["一行目。", "二行目。", "三行目。"],
    btc_comment="BTC のまとめ。",
    bullish=["強気の材料。"],
    bearish=["弱気の材料。"],
    conclusion="まとめ。",
)


@pytest.fixture
def view(fake_yfinance, fake_bitbank):
    fake_yfinance(YF_PRE_OPEN_FIXTURE)
    fake_bitbank(BITBANK_FIXTURE)
    ctx = RunContext(now=YF_PRE_OPEN_CAPTURED_AT, watchlist=load_watchlist(CONFIG_DIR))
    keys = ["markets", "sectors", "btc", "crypto_watchlist", "stock_watchlist"]
    builders = [build_markets, build_sectors, build_btc, build_crypto_watchlist, build_stock_watchlist]
    sections = []
    for key, builder in zip(keys, builders, strict=True):
        content = builder(ctx)
        sections.append(
            Section(key=key, title=key, status=STATUS_OK, basis=content.basis, sources=content.sources)
        )
    sections.append(Section(key="news", title="主要ニュース", status=STATUS_FAILED))
    ctx.data["synthesis"] = SYNTHESIS
    return build_view(ctx, sections, ReportMeta(generated_at=YF_PRE_OPEN_CAPTURED_AT))


# --- ビューモデル ------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,expected",
    [
        ("25.3（売られすぎ）", ("25.3", "売られすぎ")),
        ("混在（75 > 25 > 200）", ("混在", "75 > 25 > 200")),
        ("上昇の並び（25 > 75）（200本は算出不可）", ("上昇の並び", "25 > 75・200本は算出不可")),
        ("シグナルの下・0より下", ("シグナルの下", "0より下")),
        ("雲の下", ("雲の下", "")),
    ],
)
def test_split_label(label, expected):
    assert split_label(label) == expected


def test_view_uses_report_notation_and_is_json_serializable(view):
    json.dumps(view, ensure_ascii=False)  # JSON にできること

    assert view["summary"]["stance"] == "リスクオフ"
    hero = view["markets"]["hero"]
    assert (hero["name"], hero["value"]) == ("BTC/JPY", "10,344,652")  # bitbank の実データ
    tiles = {t["name"]: t for t in view["markets"]["tiles"]}
    assert tiles["S&P500"]["value"] == "7,416.59" and tiles["S&P500"]["pct_label"] == "-1.92%"
    assert tiles["米10年債利回り"]["pct"] is None  # 利回りは前日比%を出さない
    assert tiles["米10年債利回り"]["change"] == "-3.3bp"
    daily = view["btc"]["timeframes"][0]
    assert (daily["label"], daily["verdict"], daily["total"]) == ("日足", "弱気", -4)
    assert daily["signals"][3]["main"] == "25.6" and daily["signals"][3]["detail"] == "売られすぎ"
    assert view["btc"]["comment"] == "BTC のまとめ。"
    assert view["crypto"]["rows"][1]["vs_btc_label"] == "+1.51pt"  # XRP
    assert view["news"] is None and view["failed_sections"] == ["主要ニュース"]


# --- グラフの部品 ------------------------------------------------------------------


def test_bar_widths_scale_to_largest_absolute_value():
    rows = add_bar_widths(
        [{"pct": 2.0}, {"pct": -4.0}, {"pct": 0.0}, {"failed": True}, {"pct": None}]
    )

    assert [(r["bar"], r["dir"]) for r in rows] == [(50.0, 1), (100.0, -1), (0.0, 0), (0.0, 0), (0.0, 0)]


def test_rsi_domain_includes_guides_and_data():
    assert rsi_domain([21.9, 32.6], 30, 70) == (10.0, 80.0)
    assert rsi_domain([85.0], 30, 70) == (20.0, 90.0)


def test_rsi_svg_marks_last_value_and_escapes_dates():
    svg = rsi_svg([{"date": "11/17", "value": 25.6}, {"date": "<b>", "value": 25.3}])

    assert svg.startswith('<svg class="rsi"')
    assert ">25.3</text>" in svg  # 最新の値を端に添える
    assert "<b>" not in svg and "&lt;b&gt;" in svg
    assert rsi_svg([]) == ""


# --- HTML ----------------------------------------------------------------------------


def test_render_html_contains_sections(view):
    html = render_html(view)

    assert html.startswith("<!doctype html>")
    assert "▼</span>リスクオフ" in html
    assert "10,344,652" in html
    assert "日足 RSI(14) の推移" in html and '<svg class="rsi"' in html
    assert "取得失敗" in html  # ニュースのセクション
    assert "prefers-color-scheme: dark" in html  # ダークモードの色


def test_untrusted_text_is_escaped_and_bad_links_dropped(view):
    view = dict(view)
    view["status"] = {**view["status"], "news": STATUS_OK}
    view["news"] = [
        {
            "title": "<script>alert(1)</script>",
            "url": "javascript:alert(1)",
            "source": "x",
            "category": "暗号資産",
            "published": None,
            "summary": "<img src=x onerror=alert(1)>",
            "implication": None,
            "snippet": None,
        }
    ]

    html = render_html(view)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html
    assert 'href="javascript:' not in html


@pytest.mark.parametrize(
    "url,expected",
    [("https://www.coindesk.com/a", "https://www.coindesk.com/a"), ("javascript:alert(1)", ""), (None, "")],
)
def test_safe_url(url, expected):
    assert safe_url(url) == expected


def test_saved_view_round_trips_and_old_views_are_upgraded(view, tmp_path):
    for tf in view["btc"]["timeframes"]:
        for sg in tf["signals"]:
            sg.pop("main"), sg.pop("detail")  # 古い形式（見出し・補足がない）

    save_view(view, "2026-11-17", tmp_path)
    loaded = upgrade_view(load_view("2026-11-17", tmp_path))

    assert loaded["btc"]["timeframes"][0]["signals"][3]["main"] == "25.6"
    assert "25.6" in render_html(loaded)


# --- 画像のカード ----------------------------------------------------------------------


def test_card_html_contains_the_glance_items(view):
    from good_morning.visual.card import render_card_html

    html = render_card_html(view)

    assert "▼ リスクオフ" in html
    assert "10,344,652" in html and "（24時間）" in html
    assert "日足</span><span class=\"down\">▼ 弱気 -4" in html
    assert "S&amp;P500" in html and "7,416.59" in html
    assert "投資助言ではありません" in html


def test_card_png_is_skipped_without_playwright(view, tmp_path, monkeypatch):
    import sys

    from good_morning.visual.card import render_card_png

    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)  # import が失敗する状態

    assert render_card_png(view, tmp_path / "card.png") is None


def test_card_png_renders_with_local_chromium(view, tmp_path):
    """手元に Chromium が入っていれば、実際に PNG を作れること（ネットワークは使わない）"""
    pytest.importorskip("playwright.sync_api")
    from good_morning.visual.card import render_card_png

    out = render_card_png(view, tmp_path / "card.png")
    if out is None:
        pytest.skip("Chromium が起動できない環境（python -m playwright install chromium が必要）")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
