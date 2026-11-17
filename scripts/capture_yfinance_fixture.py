"""yfinance の日足を取得して、テスト用の固定データ（tests/fixtures/yfinance/）に保存する

テストはネットワークに依存させない方針のため、実データをこの形式で保存して使う。
対象は config/markets.yaml のマーケット一覧・セクターと、watchlist.example.yaml の米国株。

使い方:
    .venv/bin/python scripts/capture_yfinance_fixture.py            # 既定のファイル名で保存
    .venv/bin/python scripts/capture_yfinance_fixture.py out.json
"""

import json
import math
import sys
from pathlib import Path

import yfinance as yf

from good_morning.collector.market_data import HISTORY_PERIOD
from good_morning.markets.config import load_markets_config
from good_morning.paths import CONFIG_DIR, PROJECT_ROOT
from good_morning.timeutil import now_jst
from good_morning.watchlist import load_watchlist

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "yfinance"


def capture(tickers: list[str]) -> dict:
    captured_at = now_jst()
    series = {}
    for ticker in tickers:
        history = yf.Ticker(ticker).history(
            period=HISTORY_PERIOD, interval="1d", auto_adjust=False, actions=False
        )
        if history.empty:
            print(f"✗ {ticker}: 空")
            continue
        rows = [
            [ts.isoformat(), None if math.isnan(close) else round(float(close), 6)]
            for ts, close in history["Close"].items()
        ]
        series[ticker] = {"timezone": str(history.index.tz), "rows": rows}
        print(f"✓ {ticker}: {len(rows)}本")
    return {"captured_at": captured_at.isoformat(), "period": HISTORY_PERIOD, "series": series}


def main() -> None:
    config = load_markets_config()
    watchlist = load_watchlist(CONFIG_DIR)  # watchlist.yaml がなければ example
    tickers = [m.ticker for m in config.markets] + [s.ticker for s in config.sectors]
    tickers += [s.ticker for s in watchlist.stocks if s.ticker not in tickers]

    data = capture(tickers)
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
    else:
        out = FIXTURE_DIR / f"history_{now_jst():%Y%m%d_%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"保存: {out}")


if __name__ == "__main__":
    main()
