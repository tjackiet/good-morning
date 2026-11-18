"""FRED API から経済指標の発表予定日を取得する

使うのは fred/releases/dates に include_release_dates_with_no_data=true を付けたもの
（まだデータのない将来の発表日も返る）。返るのは日付だけで、時刻は返らない。

API キーは環境変数 FRED_API_KEY で渡す。httpx の例外メッセージにはリクエストの URL
（＝ API キー）が入るため、エラーの文言には URL を入れず、キーの文字列も伏せる。
"""

import logging
import os
from dataclasses import dataclass
from datetime import date

import httpx

from good_morning.errors import cause_chain
from good_morning.net import ssl_context

logger = logging.getLogger(__name__)

FRED_RELEASE_DATES_URL = "https://api.stlouisfed.org/fred/releases/dates"
FRED_API_KEY_ENV = "FRED_API_KEY"
PAGE_LIMIT = 1000
TIMEOUT_SECONDS = 30
USER_AGENT = "good-morning/0.1"


class FredError(Exception):
    """FRED から取得できなかった（メッセージに URL や API キーは入れない）"""


@dataclass(frozen=True)
class ReleaseDate:
    release_id: int
    release_name: str
    date: date


def get_api_key() -> str:
    key = os.environ.get(FRED_API_KEY_ENV, "").strip()
    if not key:
        raise FredError(f"環境変数 {FRED_API_KEY_ENV} が設定されていません（.env を確認）")
    return key


def _scrub(message: str, api_key: str) -> str:
    return message.replace(api_key, "***") if api_key else message


def parse_release_dates(payload: dict) -> list[ReleaseDate]:
    rows = []
    for item in payload.get("release_dates", []):
        try:
            rows.append(
                ReleaseDate(
                    release_id=int(item["release_id"]),
                    release_name=str(item["release_name"]),
                    date=date.fromisoformat(item["date"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def fetch_release_dates(start: date, end: date, api_key: str | None = None) -> list[ReleaseDate]:
    """start〜end の発表予定日を返す（日付の昇順。ページをまたいで取得する）"""
    api_key = api_key or get_api_key()
    params = {
        "api_key": api_key,
        "file_type": "json",
        "realtime_start": start.isoformat(),
        "include_release_dates_with_no_data": "true",
        "order_by": "release_date",
        "sort_order": "asc",
        "limit": PAGE_LIMIT,
    }

    results: list[ReleaseDate] = []
    offset = 0
    while True:
        try:
            response = httpx.get(
                FRED_RELEASE_DATES_URL,
                params={**params, "offset": offset},
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT_SECONDS,
                verify=ssl_context(),
            )
        except Exception as e:  # noqa: BLE001
            # from None: 元の例外（メッセージに URL＝API キーを含む）をログのトレースバックに残さない
            raise FredError(f"FRED に接続できませんでした（{cause_chain(e)}）") from None

        if response.status_code != 200:
            try:
                detail = str(response.json().get("error_message", ""))[:200]
            except (ValueError, AttributeError):  # JSON でない応答は状態コードだけ残す
                detail = ""
            raise FredError(_scrub(f"FRED が HTTP {response.status_code} を返しました {detail}", api_key))

        try:
            payload = response.json()
        except ValueError:
            raise FredError("FRED の応答が JSON ではありません") from None

        page = parse_release_dates(payload)
        results.extend(r for r in page if start <= r.date <= end)

        offset += PAGE_LIMIT
        count = int(payload.get("count", 0) or 0)
        # 昇順なので、end を過ぎた日付が出たらそれ以降は不要
        if not page or page[-1].date > end or offset >= count:
            break

    logger.info("FRED: %d 件の発表予定を取得（%s〜%s）", len(results), start, end)
    return results
