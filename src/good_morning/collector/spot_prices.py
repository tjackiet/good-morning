"""海外の取引所の BTC の現物価格を取得する（Coinbase プレミアム・日本プレミアム用。キー不要）

- Coinbase: GET https://api.exchange.coinbase.com/products/BTC-USD/ticker（price・time）
- Binance: GET https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT（price。時刻は返らない）
- bitbank: GET https://public.bitbank.cc/btc_jpy/ticker（data.last・data.timestamp）

プレミアムは価格どうしの差なので、取得はなるべく間を空けずに続けて行う（呼ぶ側で続けて呼ぶ）。
bitbank の価格は bitbank-lab-mcp でもマーケット一覧の最初に取っているが、プレミアムを出すころには
1分ほどたっている（2026-11-20 の実行で 54 秒）ので、日本プレミアムには公開 API の値を続けて取って使う。
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from good_morning.errors import cause_chain
from good_morning.net import ssl_context

logger = logging.getLogger(__name__)

COINBASE_TICKER_URL = "https://api.exchange.coinbase.com/products/{product}/ticker"
BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"
BITBANK_TICKER_URL = "https://public.bitbank.cc/{pair}/ticker"
TIMEOUT_SECONDS = 10
USER_AGENT = "good-morning/0.1"


class SpotPriceError(Exception):
    """現物価格を取得できなかった"""


@dataclass(frozen=True)
class SpotPrice:
    venue: str  # 表示名（Coinbase / Binance）
    symbol: str  # BTC-USD / BTCUSDT
    price: float
    time: datetime  # 取引所の時刻（返らなければ取得した時刻）


def _get(url: str, venue: str, params: dict | None = None) -> dict:
    try:
        response = httpx.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
            verify=ssl_context(),
        )
    except Exception as e:  # noqa: BLE001
        raise SpotPriceError(f"{venue} に接続できませんでした（{cause_chain(e)}）") from None
    if response.status_code != 200:
        raise SpotPriceError(f"{venue} が HTTP {response.status_code} を返しました")
    try:
        payload = response.json()
    except ValueError:
        raise SpotPriceError(f"{venue} の応答が JSON ではありません") from None
    if not isinstance(payload, dict):
        raise SpotPriceError(f"{venue} の応答の形が想定と違います")
    return payload


def _price(payload: dict, venue: str) -> float:
    try:
        price = float(payload["price"])
    except (KeyError, TypeError, ValueError):
        raise SpotPriceError(f"{venue} の応答に価格がありません") from None
    if price <= 0:
        raise SpotPriceError(f"{venue} の価格が正の数ではありません")
    return price


def parse_coinbase(payload: dict, product: str, fetched_at: datetime) -> SpotPrice:
    time = fetched_at
    if isinstance(payload.get("time"), str):
        try:  # 例 2026-11-20T00:56:45.187954405Z（小数9桁も Python 3.12 で読める）
            time = datetime.fromisoformat(payload["time"])
        except ValueError:
            time = fetched_at
    return SpotPrice(venue="Coinbase", symbol=product, price=_price(payload, "Coinbase"), time=time)


def parse_binance(payload: dict, symbol: str, fetched_at: datetime) -> SpotPrice:
    return SpotPrice(venue="Binance", symbol=symbol, price=_price(payload, "Binance"), time=fetched_at)


def fetch_coinbase(product: str = "BTC-USD") -> SpotPrice:
    payload = _get(COINBASE_TICKER_URL.format(product=product), "Coinbase")
    return parse_coinbase(payload, product, datetime.now(UTC))


def fetch_binance(symbol: str = "BTCUSDT") -> SpotPrice:
    payload = _get(BINANCE_PRICE_URL, "Binance", {"symbol": symbol})
    return parse_binance(payload, symbol, datetime.now(UTC))


def parse_bitbank(payload: dict, pair: str, fetched_at: datetime) -> SpotPrice:
    if payload.get("success") != 1 or not isinstance(payload.get("data"), dict):
        raise SpotPriceError("bitbank の応答の形が想定と違います")
    data = payload["data"]
    time = fetched_at
    if isinstance(data.get("timestamp"), int | float):
        time = datetime.fromtimestamp(data["timestamp"] / 1000, tz=UTC)
    return SpotPrice(venue="bitbank", symbol=pair, price=_price({"price": data.get("last")}, "bitbank"), time=time)


def fetch_bitbank(pair: str = "btc_jpy") -> SpotPrice:
    if not pair.replace("_", "").isalnum():
        raise SpotPriceError("bitbank のペアの名前が不正です")
    payload = _get(BITBANK_TICKER_URL.format(pair=pair), "bitbank")
    return parse_bitbank(payload, pair, datetime.now(UTC))
