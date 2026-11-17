"""bitbank-lab-mcp の structuredContent を取得して、テスト用の固定データに保存する

analyze_indicators の応答は1本で約1MBあるため、使う部分だけを残して小さくする:
  - data.indicators のスカラー値と、系列（*_series）の末尾 KEEP_BARS 本
  - data.normalized（足）の末尾 KEEP_BARS 本
  - meta
系列と足はどちらも「最新の足」で終わるので、末尾をそろえて切っても位置は対応したまま。
一目の雲（shift=26 本前）を計算できるよう、KEEP_BARS は shift より十分大きくしておく。

使い方:
    .venv/bin/python scripts/capture_bitbank_fixture.py
"""

import json
import sys
from pathlib import Path

from good_morning.collector.bitbank_mcp import fetch_snapshot, snapshot_calls
from good_morning.paths import PROJECT_ROOT
from good_morning.timeutil import now_jst

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "bitbank"
KEEP_BARS = 60


def _trim_series(value):
    if isinstance(value, list):
        return value[-KEEP_BARS:]
    if isinstance(value, dict):
        return {k: _trim_series(v) for k, v in value.items()}
    return value


def trim_indicators(structured: dict) -> dict:
    data = structured["data"]
    return {
        "ok": structured.get("ok"),
        "summary": str(structured.get("summary", ""))[:300],
        "data": {
            "indicators": {k: _trim_series(v) for k, v in data["indicators"].items()},
            "normalized": data["normalized"][-KEEP_BARS:],
        },
        "meta": structured.get("meta"),
    }


def trim_tickers(structured: dict) -> dict:
    return {
        "ok": structured.get("ok"),
        "summary": structured.get("summary"),
        "data": {"items": structured["data"]["items"]},
        "meta": structured.get("meta"),
    }


def main() -> None:
    snapshot = fetch_snapshot(snapshot_calls())
    results = {}
    for key, structured in snapshot.results.items():
        results[key] = trim_tickers(structured) if key == "tickers_jpy" else trim_indicators(structured)
        print(f"✓ {key}")
    for key, error in snapshot.errors.items():
        print(f"✗ {key}: {error}")

    data = {"captured_at": now_jst().isoformat(), "results": results, "errors": snapshot.errors}
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else FIXTURE_DIR / f"snapshot_{now_jst():%Y%m%d_%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"保存: {out}（{out.stat().st_size // 1024} KB）")


if __name__ == "__main__":
    main()
