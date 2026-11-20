"""SoSoValue の API から、BTC 現物ETF の資金流出入（日次）を取得する

使うのは次の2つ（文書: https://sosovalue-1.gitbook.io/sosovalue-api-doc 、2026-11-20 に確認）。
- 合計: GET /etfs/summary-history?symbol=BTC&country_code=US（全銘柄の合計の純流入・累計・純資産）
- 銘柄別: GET /etfs/{ticker}/history（IBIT などの純流入・累計・純資産）

資金の流出入は翌営業日に確定する（T+1）。当日の行はあっても、純流入などの値は null のまま返る
ので、null の行は「未確定」として扱う。金額はすべてドル。上限は 1分20回・1か月10万回。

API キーは環境変数 SOSO_API_KEY で渡す（ヘッダー x-soso-api-key）。httpx の例外メッセージは
使わず型名だけを残し、エラーの文言にキーの文字列が入らないよう伏せる（collector/fred.py と同じ扱い）。
Farside（farside.co.uk）はプログラムからの取得を Cloudflare で止めているため使わない。
"""

import logging
import os
from dataclasses import dataclass
from datetime import date

import httpx

from good_morning.errors import cause_chain
from good_morning.net import ssl_context

logger = logging.getLogger(__name__)

BASE_URL = "https://openapi.sosovalue.com/openapi/v1"
API_KEY_ENV = "SOSO_API_KEY"
TIMEOUT_SECONDS = 20
USER_AGENT = "good-morning/0.1"
SUCCESS_CODES = (0, 200)


class SoSoValueError(Exception):
    """SoSoValue から取得できなかった（メッセージに API キーは入れない）"""


@dataclass(frozen=True)
class FlowDay:
    """1営業日の資金流出入（ドル）。確定前の日は net_inflow などが None"""

    date: date
    net_inflow: float | None
    cum_inflow: float | None = None
    net_assets: float | None = None
    value_traded: float | None = None

    @property
    def settled(self) -> bool:
        return self.net_inflow is not None


def get_api_key() -> str:
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise SoSoValueError(f"環境変数 {API_KEY_ENV} が設定されていません（.env を確認）")
    return key


def _scrub(message: str, api_key: str) -> str:
    return message.replace(api_key, "***") if api_key else message


def _number(value) -> float | None:
    """数値・数字の文字列を float に。null・空・数字でないものは None"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def unwrap(payload) -> list[dict]:
    """応答から行のリストを取り出す（{"code", "message", "data"} で包まれていてもいなくても）"""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        code = payload.get("code")
        if code is not None and code not in SUCCESS_CODES:
            message = str(payload.get("message", ""))[:200]
            raise SoSoValueError(f"SoSoValue がエラーを返しました（code {code}: {message}）")
        data = payload.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):  # 1件だけ返る形
            return [data]
    raise SoSoValueError("SoSoValue の応答の形が想定と違います")


def _parse(rows: list[dict], fields: dict[str, str]) -> list[FlowDay]:
    """fields: FlowDay の項目名 → 応答の項目名。日付の新しい順に並べて返す"""
    days = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row["date"])[:10])
        except (KeyError, ValueError):
            continue
        days.append(FlowDay(date=day, **{k: _number(row.get(v)) for k, v in fields.items()}))
    return sorted(days, key=lambda d: d.date, reverse=True)


SUMMARY_FIELDS = {
    "net_inflow": "total_net_inflow",
    "cum_inflow": "cum_net_inflow",
    "net_assets": "total_net_assets",
    "value_traded": "total_value_traded",
}
FUND_FIELDS = {
    "net_inflow": "net_inflow",
    "cum_inflow": "cum_inflow",
    "net_assets": "net_assets",
    "value_traded": "value_traded",
}


def parse_summary(payload) -> list[FlowDay]:
    return _parse(unwrap(payload), SUMMARY_FIELDS)


def parse_fund_history(payload) -> list[FlowDay]:
    return _parse(unwrap(payload), FUND_FIELDS)


def _get(path: str, params: dict | None, api_key: str):
    try:
        response = httpx.get(
            f"{BASE_URL}{path}",
            params=params,
            headers={"x-soso-api-key": api_key, "User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
            verify=ssl_context(),
        )
    except Exception as e:  # noqa: BLE001
        raise SoSoValueError(f"SoSoValue に接続できませんでした（{cause_chain(e)}）") from None

    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code != 200:
        detail = ""
        if isinstance(payload, dict):
            detail = f"（code {payload.get('code')}: {str(payload.get('message', ''))[:200]}）"
        raise SoSoValueError(_scrub(f"SoSoValue が HTTP {response.status_code} を返しました{detail}", api_key))
    if payload is None:
        raise SoSoValueError("SoSoValue の応答が JSON ではありません")
    return payload


def fetch_summary_history(
    symbol: str = "BTC", country_code: str = "US", limit: int = 10, api_key: str | None = None
) -> list[FlowDay]:
    """全銘柄の合計の資金流出入（新しい順。直近1か月まで）"""
    api_key = api_key or get_api_key()
    payload = _get(
        "/etfs/summary-history", {"symbol": symbol, "country_code": country_code, "limit": limit}, api_key
    )
    days = parse_summary(payload)
    logger.info("SoSoValue: %s %s ETF の合計 %d 日分を取得", country_code, symbol, len(days))
    return days


def fetch_fund_history(ticker: str, api_key: str | None = None) -> list[FlowDay]:
    """1銘柄の資金流出入（新しい順。直近1か月まで）"""
    api_key = api_key or get_api_key()
    days = parse_fund_history(_get(f"/etfs/{ticker}/history", None, api_key))
    logger.info("SoSoValue: %s %d 日分を取得", ticker, len(days))
    return days
