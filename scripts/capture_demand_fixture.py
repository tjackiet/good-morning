"""暗号資産の需給（ステーブルコイン・プレミアム）のテスト用の固定データを保存する

→ tests/fixtures/demand/demand_YYYYMMDD_HHMM.json
- DefiLlama の合計の推移（直近20日分だけに切り詰める。全期間だと約1.4MB）と、銘柄ごとの一覧
  （config/demand.yaml の内訳の銘柄だけに切り詰める）
- bitbank（公開 API）・Binance・Coinbase の BTC の現物価格の生の応答（続けて取得）
- 予備の bitbank の BTC/JPY（bitbank-lab-mcp）とドル円（マーケット一覧と同じ取り方で取得した値）

使い方:
    .venv/bin/python scripts/capture_demand_fixture.py
"""

import json

import httpx

from good_morning.collector import defillama, spot_prices
from good_morning.context import RunContext
from good_morning.demand.builder import _bitbank_btc, _usdjpy
from good_morning.demand.config import load_demand_config
from good_morning.markets.builders import build_markets
from good_morning.net import ssl_context
from good_morning.paths import CONFIG_DIR, PROJECT_ROOT
from good_morning.timeutil import now_jst
from good_morning.watchlist import load_watchlist

FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "demand"
PEGS = ("peggedUSD", "peggedEUR", "peggedJPY")
ASSET_KEYS = ("id", "name", "symbol", "pegType", "circulating", "circulatingPrevDay", "circulatingPrevWeek")


def _raw(url: str, params: dict | None = None):
    response = httpx.get(
        url, params=params, headers={"User-Agent": "good-morning/0.1"}, timeout=30, verify=ssl_context()
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    config = load_demand_config()
    now = now_jst()
    ctx = RunContext(now=now, watchlist=load_watchlist(CONFIG_DIR, quiet=True))
    build_markets(ctx)
    btc = _bitbank_btc(ctx)

    # 使う項目だけに切り詰める（合計はドル連動のほか、選ばないことを確かめる用に EUR・JPY を残す）
    totals = [
        {"date": r["date"], "totalCirculatingUSD": {k: v for k, v in r["totalCirculatingUSD"].items() if k in PEGS}}
        for r in _raw(defillama.CHARTS_URL)[-20:]
    ]
    assets = {
        "peggedAssets": [
            {k: a.get(k) for k in ASSET_KEYS}
            for a in _raw(defillama.ASSETS_URL, {"includePrices": "false"})["peggedAssets"]
            if a.get("symbol") in config.stablecoins.breakdown
        ]
    }
    # 本番と同じ順に続けて取る（bitbank → Binance → Coinbase）
    bitbank = _raw(spot_prices.BITBANK_TICKER_URL.format(pair="btc_jpy"))
    binance = _raw(spot_prices.BINANCE_PRICE_URL, {"symbol": config.premium.reference_symbol})
    coinbase = _raw(spot_prices.COINBASE_TICKER_URL.format(product=config.premium.coinbase_product))

    payload = {
        "captured_at": now.isoformat(),
        "defillama_totals": totals,
        "defillama_assets": assets,
        "binance": binance,
        "coinbase": coinbase,
        "bitbank": bitbank,
        # 公開 API が取れなかったときの予備（マーケット一覧で bitbank-lab-mcp から取った値）
        "bitbank_btc_jpy": {"last": btc.last, "timestamp": btc.timestamp.isoformat()} if btc else None,
        "usdjpy": _usdjpy(ctx),
    }
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / f"demand_{now:%Y%m%d_%H%M}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"保存しました: {path.relative_to(PROJECT_ROOT)}（{path.stat().st_size:,} バイト）")


if __name__ == "__main__":
    main()
