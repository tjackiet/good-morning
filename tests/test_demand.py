"""暗号資産の需給（ステーブルコインの供給量・プレミアム）のテスト（ネットワークなし）"""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from conftest import JST, load_fixture_json

from good_morning.collector import defillama, spot_prices
from good_morning.collector.defillama import DefiLlamaError, parse_assets, parse_totals
from good_morning.collector.spot_prices import (
    SpotPriceError,
    parse_binance,
    parse_bitbank,
    parse_coinbase,
)
from good_morning.context import RunContext
from good_morning.demand.builder import (
    DemandError,
    build_crypto_demand,
    coinbase_premium,
    japan_premium,
    oku_change_label,
    oku_label,
    pct_label,
    stablecoin_supply,
    usd_label,
)
from good_morning.demand.config import load_demand_config
from good_morning.markets.quotes import Quote
from good_morning.reporter.markdown import STATUS_OK, ReportMeta, Section
from good_morning.synthesis.facts import build_facts

# 2026-11-20 10:09 JST に取得した実データ（DefiLlama、続けて取った bitbank・Binance・Coinbase、ドル円）
FIXTURE = "demand/demand_20261120_1009.json"
NOW = datetime(2026, 11, 20, 10, 9, tzinfo=JST)
FETCHED = datetime(2026, 11, 20, 1, 10, 2, tzinfo=UTC)


def _data():
    return load_fixture_json(FIXTURE)


def _usdjpy_quote(value: float) -> Quote:
    return Quote(
        ticker="JPY=X", name="ドル円", basis="live", format="price", decimals=2,
        last=value, prev=value, last_date=NOW.date(), prev_date=NOW.date(),
    )  # fmt: skip


@pytest.fixture
def fake_demand(monkeypatch):
    """DefiLlama・Binance・Coinbase・bitbank を固定データで差し替え、ctx を返す"""

    def _install(failing: tuple[str, ...] = (), bitbank: bool = True, usdjpy: bool = True):
        """failing: 失敗させる取得（totals・assets・binance・coinbase・bitbank）。
        "bitbank" は公開 API だけの失敗（予備の bitbank-lab-mcp の値は残る）。bitbank=False は予備もない"""
        data = _data()
        config = load_demand_config()
        if not bitbank:
            failing = (*failing, "bitbank")

        def stub(name, error, value):
            def _f(*args, **kwargs):
                if name in failing:
                    raise error("テスト用の失敗")
                return value()

            return _f

        def totals():
            return parse_totals(data["defillama_totals"])

        def assets():
            return parse_assets(data["defillama_assets"], config.stablecoins.breakdown)

        monkeypatch.setattr(defillama, "fetch_totals", stub("totals", DefiLlamaError, totals))
        monkeypatch.setattr(defillama, "fetch_assets", stub("assets", DefiLlamaError, assets))
        for name, parse, raw, symbol in (
            ("bitbank", parse_bitbank, data["bitbank"], "btc_jpy"),
            ("binance", parse_binance, data["binance"], "BTCUSDT"),
            ("coinbase", parse_coinbase, data["coinbase"], "BTC-USD"),
        ):
            value = (lambda p=parse, r=raw, s=symbol: p(r, s, FETCHED))
            monkeypatch.setattr(spot_prices, f"fetch_{name}", stub(name, SpotPriceError, value))
        btc = data["bitbank_btc_jpy"]
        ticker = SimpleNamespace(last=btc["last"], timestamp=datetime.fromisoformat(btc["timestamp"]))
        monkeypatch.setattr("good_morning.demand.builder._bitbank_btc", lambda ctx: ticker if bitbank else None)
        ctx = RunContext(now=NOW)
        if usdjpy:
            ctx.data["markets"] = [_usdjpy_quote(data["usdjpy"])]
        return ctx

    return _install


# --- 取得（応答の読み取り） ---------------------------------------------------------


def test_shipped_config():
    config = load_demand_config()
    assert (config.stablecoins.change_days, config.stablecoins.breakdown) == (7, ["USDT", "USDC"])
    assert (config.premium.coinbase_product, config.premium.reference_symbol) == ("BTC-USD", "BTCUSDT")


def test_parse_totals_uses_usd_pegged_and_sorts():
    points = parse_totals(_data()["defillama_totals"])

    assert points[-1].date == date(2026, 11, 20)
    assert points[-1].total == pytest.approx(283639880509.28)  # ドル連動だけ（EUR・JPY は足さない）
    assert [p.date for p in points] == sorted(p.date for p in points)


def test_parse_assets_picks_usd_pegged_and_the_larger_duplicate():
    payload = {
        "peggedAssets": [
            {"symbol": "USDT", "pegType": "peggedUSD", "circulating": {"peggedUSD": 10.0}},
            {"symbol": "USDT", "pegType": "peggedUSD", "circulating": {"peggedUSD": 100.0}},  # 多いほう
            {"symbol": "USDC", "pegType": "peggedEUR", "circulating": {"peggedEUR": 5.0}},  # ドル連動でない
        ]
    }
    coins = parse_assets(payload, ["USDT", "USDC"])

    assert list(coins) == ["USDT"] and coins["USDT"].current == 100.0 and coins["USDT"].prev_week is None
    with pytest.raises(DefiLlamaError):
        parse_assets({"unexpected": []}, ["USDT"])


def test_parse_spot_prices():
    data = _data()
    cb = parse_coinbase(data["coinbase"], "BTC-USD", FETCHED)
    bn = parse_binance(data["binance"], "BTCUSDT", FETCHED)

    assert (cb.price, bn.price) == (62377.68, 62463.03)
    assert cb.time == datetime(2026, 11, 20, 1, 10, 2, 575826, tzinfo=UTC)  # 小数9桁の時刻
    with pytest.raises(SpotPriceError):
        parse_binance({"symbol": "BTCUSDT"}, "BTCUSDT", FETCHED)
    with pytest.raises(SpotPriceError):
        parse_coinbase({"price": "0"}, "BTC-USD", FETCHED)


class _Response:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def test_http_errors_are_reported_without_details(monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *a, **k: _Response(503))
    with pytest.raises(DefiLlamaError, match="HTTP 503"):
        defillama.fetch_totals()
    with pytest.raises(SpotPriceError, match="Coinbase が HTTP 503"):
        spot_prices.fetch_coinbase()

    def broken(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr("httpx.get", broken)
    with pytest.raises(SpotPriceError, match="Binance に接続できませんでした（TimeoutError）"):
        spot_prices.fetch_binance()


# --- 計算と表記 ------------------------------------------------------------------------


def test_stablecoin_changes_come_from_the_daily_totals():
    data = _data()
    config = load_demand_config()
    points = parse_totals(data["defillama_totals"])
    by_date = {p.date: p.total for p in points}

    s = stablecoin_supply(points, parse_assets(data["defillama_assets"], ["USDT", "USDC"]), config)

    assert s.date == date(2026, 11, 20)
    assert s.day_change == pytest.approx(by_date[date(2026, 11, 20)] - by_date[date(2026, 11, 19)])
    assert s.period_change == pytest.approx(by_date[date(2026, 11, 20)] - by_date[date(2026, 11, 13)])
    assert [c.symbol for c in s.coins] == ["USDT", "USDC"]


def test_premiums_from_real_prices():
    data = _data()
    cb = parse_coinbase(data["coinbase"], "BTC-USD", FETCHED)
    bn = parse_binance(data["binance"], "BTCUSDT", FETCHED)

    bb = parse_bitbank(data["bitbank"], "btc_jpy", FETCHED)

    coinbase = coinbase_premium(cb, bn)
    japan = japan_premium(bb.price, data["usdjpy"], cb)

    assert bb.price == 9956197 and bb.time == datetime(2026, 11, 20, 1, 10, 1, 190000, tzinfo=UTC)
    assert (pct_label(coinbase.pct), usd_label(coinbase.diff_usd, signed=True)) == ("-0.14%", "-85ドル")
    assert coinbase.detail == "Coinbase BTC-USD 62,378ドル／Binance BTC-USDT 62,463ドル"
    assert (pct_label(japan.pct), usd_label(japan.diff_usd, signed=True)) == ("+0.17%", "+105ドル")
    assert japan.detail == "bitbank BTC/JPY 9,956,197円 ÷ ドル円 159.34 = 62,483ドル／Coinbase 62,378ドル"


@pytest.mark.parametrize(
    "func,value,expected",
    [
        (oku_label, 283639880509.28, "2,836"),
        (oku_change_label, -1030000000, "-10.3"),
        (oku_change_label, 4000000, "0.0"),
        (oku_change_label, None, "—"),
        (pct_label, 0.004, "0.00%"),
        (pct_label, 0.2149, "+0.21%"),
    ],
)
def test_labels(func, value, expected):
    assert func(value) == expected


# --- セクション --------------------------------------------------------------------------


def test_section_with_real_data(fake_demand):
    ctx = fake_demand()
    content = build_crypto_demand(ctx)

    assert content.body.startswith(
        "見方: ステーブルコインは増えていれば、暗号資産を買う待機資金が増えている。"
        "Coinbase プレミアムはプラスなら米国の買いが強い（マイナスなら弱い）。"
        "日本プレミアムはプラスなら国内の価格が海外より割高。"
    )
    assert "| 銘柄 | 供給量 | 前日比 | 7日の増減 |" in content.body
    assert "| 合計 | 2,836 |" in content.body and "| -41.3（-1.44%） |" in content.body
    assert "| USDT | 1,751 |" in content.body and "| USDC | 688 |" in content.body
    assert "| -4.3（-0.24%） |" in content.body
    assert "| Coinbase プレミアム | -0.14%（-85ドル） | Coinbase BTC-USD 62,378ドル／Binance BTC-USDT 62,463ドル |" in content.body
    assert "| 日本プレミアム | +0.17%（+105ドル） |" in content.body
    assert "価格の時刻（日本時間）: bitbank 10:10:01・Coinbase 10:10:02・Binance 10:10:02。" in content.body
    assert content.basis == [
        (
            "暗号資産の需給: ステーブルコインは DefiLlama の日次の値（11/20 分）、"
            "プレミアムは取得時点の価格（2026-11-20 10:09 JST ごろ）"
        )
    ]
    assert "⚠" not in content.body


def test_stablecoin_failure_keeps_premiums(fake_demand):
    content = build_crypto_demand(fake_demand(failing=("totals",)))

    assert "**ステーブルコインの供給量（ドル連動・単位は億ドル）**\n\n取得失敗" in content.body
    assert "| Coinbase プレミアム | -0.14%" in content.body
    assert "⚠ 取得できませんでした（理由はログを参照）: ステーブルコインの供給量" in content.body


def test_breakdown_failure_keeps_total(fake_demand):
    content = build_crypto_demand(fake_demand(failing=("assets",)))

    assert "| 合計 | 2,836 |" in content.body and "| USDT |" not in content.body
    assert "ステーブルコインの内訳" in content.body


def test_coinbase_failure_fails_both_premiums(fake_demand):
    content = build_crypto_demand(fake_demand(failing=("coinbase",)))

    assert "| Coinbase プレミアム | 取得失敗 | — |" in content.body
    assert "| 日本プレミアム | 取得失敗 | — |" in content.body
    assert "| 合計 | 2,836 |" in content.body


def test_missing_bitbank_or_usdjpy_fails_only_japan_premium(fake_demand):
    for options in ({"bitbank": False}, {"usdjpy": False}):
        body = build_crypto_demand(fake_demand(**options)).body  # 差し替えは呼ぶたびに入れ直す
        assert "| 日本プレミアム | 取得失敗 | — |" in body
        assert "| Coinbase プレミアム | -0.14%" in body


def test_bitbank_api_failure_falls_back_to_the_earlier_price(fake_demand):
    """公開 API で取れなければ、マーケット一覧で bitbank-lab-mcp から取った値（5秒前）を使う"""
    body = build_crypto_demand(fake_demand(failing=("bitbank",))).body

    assert "| 日本プレミアム | +0.17%（+105ドル） |" in body  # 同じ価格（9,956,197円）なので値は同じ
    assert "bitbank 10:09:56・Coinbase 10:10:02" in body  # 予備の値の時刻を添える


def test_everything_failing_raises(fake_demand):
    with pytest.raises(DemandError):
        build_crypto_demand(fake_demand(failing=("totals", "binance", "coinbase")))


def test_demand_reaches_facts_view_and_html(fake_demand):
    from good_morning.visual.render import render_html
    from good_morning.visual.viewmodel import build_view

    ctx = fake_demand()
    content = build_crypto_demand(ctx)

    facts = build_facts(ctx)
    assert "## 暗号資産の需給" in facts
    assert "- ステーブルコイン（ドル連動）の供給量（増減は億ドルと%）: 合計 2,836億ドル（11/20 分）、前日比 " in facts
    assert "、7日の増減 -41.3（-1.44%）。内訳 USDT 1,751億ドル（7日の増減 -4.3（-0.24%））" in facts
    assert "- Coinbase プレミアム: -0.14%（-85ドル。取得時点の値。プラスは米国の買いが強い）" in facts
    assert "- 日本プレミアム: +0.17%（+105ドル。取得時点の値。プラスは国内の価格が割高）" in facts

    section = Section(key="crypto_demand", title="暗号資産の需給", status=STATUS_OK, basis=content.basis)
    view = build_view(ctx, [section], ReportMeta(generated_at=NOW))
    demand = view["demand"]
    assert demand["stablecoins"]["total"] == "2,836" and demand["stablecoins"]["period_days"] == 7
    assert [p["pct_label"] for p in demand["premiums"]] == ["-0.14%", "+0.17%"]
    assert demand["times"] == "bitbank 10:10:01・Coinbase 10:10:02・Binance 10:10:02"

    html = render_html(view)
    assert '<h2 id="h-demand">暗号資産の需給' in html
    assert "▼ -1.44%</div>" in html  # プレミアムとそろえて、大きく出すのは増減率（%）
    assert "7日で -41.3億ドル</div>" in html  # 金額には単位を付ける
    assert "合計 2,836億ドルの7日の増減率" in html
    assert "USDT 1,751億ドル（7日で -0.24%・-4.3億ドル）" in html
    assert "▼ -0.14%" in html and "▲ +0.17%" in html
    assert "プレミアムの計算に使った価格" in html
    assert "<li><b>日本プレミアム</b>：プラスなら国内の価格が海外より割高</li>" in html
