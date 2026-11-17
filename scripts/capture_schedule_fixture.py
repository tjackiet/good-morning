"""今後の予定のテスト用の固定データを保存する

- 決算: ウォッチリスト（なければ example）の米国株と related の関連企業について、
  yfinance の info のうち決算日に関わる項目と、get_earnings_dates() の行を保存する
  → tests/fixtures/yfinance/earnings_YYYYMMDD_HHMM.json
- FRED: FRED_API_KEY が設定されていれば、fred/releases/dates の生の応答（1ページ目）を保存する
  → tests/fixtures/fred/release_dates_YYYYMMDD_HHMM.json（API キーは保存しない）

使い方:
    .venv/bin/python scripts/capture_schedule_fixture.py
"""

import json
import math
import os
from datetime import timedelta

import httpx
import yfinance as yf
from dotenv import load_dotenv

from good_morning.collector.fred import FRED_API_KEY_ENV, FRED_RELEASE_DATES_URL
from good_morning.paths import CONFIG_DIR, PROJECT_ROOT
from good_morning.timeutil import now_jst
from good_morning.watchlist import load_watchlist

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
INFO_KEYS = (
    "isEarningsDateEstimate",
    "earningsTimestamp",
    "earningsTimestampStart",
    "earningsTimestampEnd",
    "shortName",
)


def _num(value):
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def capture_earnings(stamp: str) -> None:
    watchlist = load_watchlist(CONFIG_DIR)
    tickers = []
    for stock in watchlist.stocks:
        for t in [stock.ticker, *stock.related]:
            if t not in tickers:
                tickers.append(t)

    earnings = {}
    for t in tickers:
        ticker = yf.Ticker(t)
        info = {k: ticker.info.get(k) for k in INFO_KEYS}
        df = ticker.get_earnings_dates(limit=8)
        rows = []
        if df is not None:
            for ts, row in df.iterrows():
                rows.append([ts.isoformat(), _num(row.get("EPS Estimate")), _num(row.get("Reported EPS"))])
        earnings[t] = {"info": info, "earnings_dates": rows}
        print(f"✓ {t}: {len(rows)} 行")

    out = FIXTURES / "yfinance" / f"earnings_{stamp}.json"
    data = {"captured_at": now_jst().isoformat(), "earnings": earnings}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"保存: {out}")


def capture_fred(stamp: str) -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get(FRED_API_KEY_ENV)
    if not api_key:
        print(f"FRED: {FRED_API_KEY_ENV} が未設定のためスキップ")
        return
    today = now_jst().date()
    response = httpx.get(
        FRED_RELEASE_DATES_URL,
        params={
            "api_key": api_key,
            "file_type": "json",
            "realtime_start": today.isoformat(),
            "include_release_dates_with_no_data": "true",
            "order_by": "release_date",
            "sort_order": "asc",
            "limit": 1000,
        },
        timeout=30,
    )
    print(f"FRED: HTTP {response.status_code}")
    payload = response.json()
    horizon = (today + timedelta(days=45)).isoformat()
    payload["release_dates"] = [r for r in payload.get("release_dates", []) if r["date"] <= horizon]
    out = FIXTURES / "fred" / f"release_dates_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"保存: {out}（{len(payload['release_dates'])} 件）")


def main() -> None:
    stamp = f"{now_jst():%Y%m%d_%H%M}"
    capture_earnings(stamp)
    capture_fred(stamp)


if __name__ == "__main__":
    main()
