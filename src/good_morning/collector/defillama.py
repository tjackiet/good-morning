"""DefiLlama の API から、ステーブルコインの供給量を取得する（キー不要）

使うのは次の2つ（2026-11-20 に実データで確認）。
- 合計の推移: GET https://stablecoins.llama.fi/stablecoincharts/all
  日ごと（UTC の 0:00）の totalCirculatingUSD。ドル連動（peggedUSD）の値を使う。全期間が返る（約1.4MB）。
- 銘柄ごと: GET https://stablecoins.llama.fi/stablecoins?includePrices=false
  銘柄ごとの circulating（取得時点）・circulatingPrevDay・circulatingPrevWeek（約0.6MB）。

合計は DefiLlama の日次の合計をそのまま使う（銘柄ごとの値を足した数とは少しずれる。足した数で
置き換えないのは、DefiLlama のサイトの合計と合わせるため）。
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from good_morning.errors import cause_chain
from good_morning.net import ssl_context

logger = logging.getLogger(__name__)

CHARTS_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
ASSETS_URL = "https://stablecoins.llama.fi/stablecoins"
PEG = "peggedUSD"
TIMEOUT_SECONDS = 30
USER_AGENT = "good-morning/0.1"


class DefiLlamaError(Exception):
    """DefiLlama から取得できなかった"""


@dataclass(frozen=True)
class SupplyPoint:
    date: date  # UTC の日付
    total: float  # ドル連動のステーブルコインの合計（ドル）


@dataclass(frozen=True)
class CoinSupply:
    symbol: str
    current: float  # 取得時点（ドル）
    prev_day: float | None
    prev_week: float | None


def _get(url: str, params: dict | None = None):
    try:
        response = httpx.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
            verify=ssl_context(),
        )
    except Exception as e:  # noqa: BLE001
        raise DefiLlamaError(f"DefiLlama に接続できませんでした（{cause_chain(e)}）") from None
    if response.status_code != 200:
        raise DefiLlamaError(f"DefiLlama が HTTP {response.status_code} を返しました")
    try:
        return response.json()
    except ValueError:
        raise DefiLlamaError("DefiLlama の応答が JSON ではありません") from None


def _peg_value(block) -> float | None:
    value = block.get(PEG) if isinstance(block, dict) else None
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def parse_totals(payload) -> list[SupplyPoint]:
    """合計の推移（古い順）"""
    if not isinstance(payload, list):
        raise DefiLlamaError("DefiLlama の応答の形が想定と違います（合計の推移）")
    points = []
    for row in payload:
        try:
            day = datetime.fromtimestamp(int(row["date"]), tz=UTC).date()
        except (KeyError, TypeError, ValueError):
            continue
        total = _peg_value(row.get("totalCirculatingUSD"))
        if total is not None:
            points.append(SupplyPoint(date=day, total=total))
    return sorted(points, key=lambda p: p.date)


def parse_assets(payload, symbols: list[str]) -> dict[str, CoinSupply]:
    """symbols の銘柄の供給量（ドル連動のものだけ。同じ記号が複数あれば供給量の多いほう）"""
    assets = payload.get("peggedAssets") if isinstance(payload, dict) else None
    if not isinstance(assets, list):
        raise DefiLlamaError("DefiLlama の応答の形が想定と違います（銘柄ごと）")
    found: dict[str, CoinSupply] = {}
    for a in assets:
        symbol = a.get("symbol")
        if symbol not in symbols or a.get("pegType") != PEG:
            continue
        current = _peg_value(a.get("circulating"))
        if current is None or (symbol in found and found[symbol].current >= current):
            continue
        found[symbol] = CoinSupply(
            symbol=symbol,
            current=current,
            prev_day=_peg_value(a.get("circulatingPrevDay")),
            prev_week=_peg_value(a.get("circulatingPrevWeek")),
        )
    return found


def fetch_totals() -> list[SupplyPoint]:
    points = parse_totals(_get(CHARTS_URL))
    logger.info("DefiLlama: ステーブルコインの合計 %d 日分を取得", len(points))
    return points


def fetch_assets(symbols: list[str]) -> dict[str, CoinSupply]:
    coins = parse_assets(_get(ASSETS_URL, {"includePrices": "false"}), symbols)
    logger.info("DefiLlama: ステーブルコイン %s を取得", "・".join(coins))
    return coins
