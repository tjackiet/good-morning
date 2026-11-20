"""BTC 現物ETF の資金流出入のテスト用の固定データを保存する

SoSoValue の生の応答（合計の summary-history と、config/etf.yaml の銘柄ごとの history）を
1つの JSON にまとめて保存する → tests/fixtures/sosovalue/etf_flows_YYYYMMDD_HHMM.json
（API キーは保存しない。応答にもキーは含まれない）

使い方:
    .venv/bin/python scripts/capture_etf_fixture.py
"""

import json

from dotenv import load_dotenv

from good_morning.collector import sosovalue
from good_morning.etf.config import load_etf_config
from good_morning.paths import PROJECT_ROOT
from good_morning.timeutil import now_jst

FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "sosovalue"


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = sosovalue.get_api_key()
    config = load_etf_config()
    now = now_jst()

    summary = sosovalue._get(
        "/etfs/summary-history",
        {"symbol": config.symbol, "country_code": config.country_code, "limit": 10},
        api_key,
    )
    print(f"✓ 合計: {len(sosovalue.unwrap(summary))} 行")
    funds = {}
    for fund in config.funds:
        try:
            funds[fund.ticker] = sosovalue._get(f"/etfs/{fund.ticker}/history", None, api_key)
            print(f"✓ {fund.ticker}: {len(sosovalue.unwrap(funds[fund.ticker]))} 行")
        except sosovalue.SoSoValueError as e:
            print(f"✗ {fund.ticker}: {e}")

    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / f"etf_flows_{now:%Y%m%d_%H%M}.json"
    payload = {"captured_at": now.isoformat(), "summary": summary, "funds": funds}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"保存しました: {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
