"""ログ設定

取得に失敗してもレポートは止めない方針のため、失敗理由はログに残す。
コンソールには INFO 以上を短い形式で、ファイル（logs/YYYY-MM-DD.log）には
時刻とモジュール名付きで書き出す。
"""

import logging
from datetime import datetime
from pathlib import Path

from good_morning.paths import LOGS_DIR
from good_morning.timeutil import now_jst

_CONFIGURED = False


def setup_logging(log_dir: Path | None = None, now: datetime | None = None) -> Path:
    """ルートロガーにコンソールとファイルの出力先を設定し、ログファイルのパスを返す"""
    global _CONFIGURED

    log_dir = log_dir or LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{(now or now_jst()).strftime('%Y-%m-%d')}.log"

    if _CONFIGURED:
        return log_path

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )

    root.addHandler(console)
    root.addHandler(file_handler)

    # ライブラリ側の細かいログ（HTTP 通信など）はファイルにも出さない
    # httpx2 は anthropic SDK 2.x が使う HTTP ライブラリ（INFO だとリクエストの URL を出す）
    for noisy in ("httpx", "httpx2", "httpcore", "anthropic", "mcp", "yfinance", "curl_cffi"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    return log_path
