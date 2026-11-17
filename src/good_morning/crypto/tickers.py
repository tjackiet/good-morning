"""bitbank のティッカー（get_tickers_jpy の structuredContent）の読み取り"""

from dataclasses import dataclass
from datetime import UTC, datetime


class TickersError(Exception):
    """ティッカーを読み取れなかった"""


@dataclass(frozen=True)
class CryptoTicker:
    pair: str
    last: float
    open: float  # 24時間前の価格
    last_text: str  # 取引所の桁数のままの文字列（表示用）
    timestamp: datetime | None

    @property
    def change_pct(self) -> float:
        """24時間の変化率（%）。ツールの change24hPct は丸められているので自前で計算する"""
        return (self.last / self.open - 1) * 100

    @property
    def label(self) -> str:
        return self.pair.replace("_", "/").upper()


def parse_tickers(structured: dict) -> dict[str, CryptoTicker]:
    try:
        items = structured["data"]["items"]
    except (KeyError, TypeError) as e:
        raise TickersError(f"get_tickers_jpy の形が想定と違います（{e}）") from e

    tickers = {}
    for item in items:
        try:
            last, open_ = float(item["last"]), float(item["open"])
        except (KeyError, TypeError, ValueError):
            continue  # 値の欠けたペアは飛ばす（照合のときに「取扱なし」と同じ扱いになる）
        if open_ <= 0:
            continue
        timestamp = None
        if item.get("timestamp"):
            timestamp = datetime.fromtimestamp(item["timestamp"] / 1000, tz=UTC)
        tickers[item["pair"]] = CryptoTicker(
            pair=item["pair"],
            last=last,
            open=open_,
            last_text=str(item["last"]),
            timestamp=timestamp,
        )
    if not tickers:
        raise TickersError("ティッカーが1件もありません")
    return tickers


def format_price_text(text: str) -> str:
    """取引所の桁数を保ったまま3桁区切りにする（例: "10367300" → "10,367,300"）"""
    integer, _, fraction = text.partition(".")
    grouped = f"{int(integer):,}"
    return f"{grouped}.{fraction}" if fraction else grouped
