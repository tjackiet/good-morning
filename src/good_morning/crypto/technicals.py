"""BTC のテクニカル指標の読み取りと判定（ネットワークに触れない純粋な処理）

bitbank-lab-mcp の analyze_indicators の structuredContent から数値だけを取り出し、
判定は config/scoring.yaml の基準でこちらが行う。ツールの文章ラベルや trend/zones は使わない。

一目均衡表の注意:
  structuredContent の ICHIMOKU_spanA/spanB と ichi_series は「ずらす前」の値
  （今の足で計算した先行スパン＝26本先に描く値）。今の足の位置にある雲は、
  shift 本前の足で計算した先行スパンなので、series[-1 - shift] を使う。
  遅行スパンは「今の終値」を shift 本前の終値と比べる。
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import pairwise
from typing import Any

from good_morning.crypto.config import ScoringConfig

TIMEFRAME_LABELS = {"1day": "日足", "1week": "週足", "1month": "月足"}


class TechnicalsError(Exception):
    """structuredContent から必要な数値を読み取れなかった"""


@dataclass(frozen=True)
class Technicals:
    timeframe: str
    close: float  # 最新の足（形成中）の終値＝取得時点の価格
    last_bar_date: date  # 最新の足の開始日（JST）
    sma: dict[int, float | None]
    rsi: float | None
    rsi_history: list[tuple[date, float | None]]  # 古い順。最後が形成中の足
    bb_sigma: float | None  # ボリンジャーバンドの σ 位置（(終値 - 中心線) / σ）
    tenkan: float | None
    kijun: float | None
    cloud_a: float | None  # 今の足の位置にある雲（先行スパン1）
    cloud_b: float | None  # 今の足の位置にある雲（先行スパン2）
    past_close: float | None  # shift 本前の終値（遅行スパンの比較相手）
    macd_line: float | None
    macd_signal: float | None
    provisional: bool = True
    fetched_at: datetime | None = None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _at(series: list | None, index: int) -> float | None:
    if not series or len(series) < abs(index):
        return None
    return _num(series[index])


def _bar_date(candle: dict) -> date:
    local = candle.get("isoTimeLocal")
    if local:
        return datetime.fromisoformat(local).date()
    raise TechnicalsError("足の日付（isoTimeLocal）がありません")


def parse_technicals(timeframe: str, structured: dict, config: ScoringConfig) -> Technicals:
    """analyze_indicators の structuredContent から Technicals を作る"""
    try:
        data = structured["data"]
        indicators = data["indicators"]
        candles = data["normalized"]
    except (KeyError, TypeError) as e:
        raise TechnicalsError(f"{timeframe}: structuredContent の形が想定と違います（{e}）") from e
    if not candles:
        raise TechnicalsError(f"{timeframe}: 足のデータがありません")

    close = _num(candles[-1].get("close"))
    if close is None:
        raise TechnicalsError(f"{timeframe}: 最新の足の終値がありません")

    period = config.rsi.period
    rsi_series = indicators.get(f"RSI_{period}_series") or []
    n = config.rsi.history_bars
    if rsi_series and len(rsi_series) != len(candles):
        raise TechnicalsError(f"{timeframe}: RSI の系列と足の本数が合いません")
    rsi_history = [
        (_bar_date(candle), _num(value))
        for candle, value in zip(candles[-n:], rsi_series[-n:], strict=False)
    ]

    middle = _num(indicators.get("BB_middle"))
    upper_1sigma = _num(indicators.get("BB1_upper"))
    bb_sigma = None
    if middle is not None and upper_1sigma is not None and upper_1sigma > middle:
        bb_sigma = (close - middle) / (upper_1sigma - middle)

    shift = config.ichimoku.shift
    ichi = indicators.get("ichi_series") or {}
    past_close = _num(candles[-1 - shift].get("close")) if len(candles) > shift else None

    meta = structured.get("meta") or {}
    fetched_at = None
    if meta.get("fetchedAt"):
        fetched_at = datetime.fromisoformat(meta["fetchedAt"])

    return Technicals(
        timeframe=timeframe,
        close=close,
        last_bar_date=_bar_date(candles[-1]),
        sma={p: _num(indicators.get(f"SMA_{p}")) for p in config.moving_average.periods},
        rsi=_num(indicators.get(f"RSI_{period}")),
        rsi_history=rsi_history,
        bb_sigma=bb_sigma,
        tenkan=_num(indicators.get("ICHIMOKU_conversion")),
        kijun=_num(indicators.get("ICHIMOKU_base")),
        cloud_a=_at(ichi.get("spanA"), -1 - shift),
        cloud_b=_at(ichi.get("spanB"), -1 - shift),
        past_close=past_close,
        macd_line=_num(indicators.get("MACD_line")),
        macd_signal=_num(indicators.get("MACD_signal")),
        provisional=bool(meta.get("provisional", True)),
        fetched_at=fetched_at,
    )


# --- 判定 -------------------------------------------------------------------

NOT_AVAILABLE = "算出不可"


@dataclass(frozen=True)
class Signal:
    label: str
    score: int  # 強気 +1・弱気 -1・中立 0


@dataclass(frozen=True)
class Assessment:
    timeframe: str
    cloud: Signal
    sanyaku: Signal
    ma_order: Signal
    rsi: Signal
    macd: Signal
    bb: str  # σ 位置の表示（点数には入れない）
    total: int
    verdict: str  # 強気／中立／弱気
    technicals: Technicals = field(repr=False, compare=False, default=None)


def _sign(a: float, b: float) -> int:
    return (a > b) - (a < b)


def cloud_signal(t: Technicals) -> Signal:
    if t.cloud_a is None or t.cloud_b is None:
        return Signal(NOT_AVAILABLE, 0)
    top, bottom = max(t.cloud_a, t.cloud_b), min(t.cloud_a, t.cloud_b)
    if t.close > top:
        return Signal("雲の上", 1)
    if t.close < bottom:
        return Signal("雲の下", -1)
    return Signal("雲の中", 0)


def sanyaku_signal(t: Technicals) -> Signal:
    """三役: 転換線と基準線、遅行スパンと過去の価格、価格と雲。3つそろえば好転／逆転"""
    if None in (t.tenkan, t.kijun, t.past_close, t.cloud_a, t.cloud_b):
        return Signal(NOT_AVAILABLE, 0)
    top, bottom = max(t.cloud_a, t.cloud_b), min(t.cloud_a, t.cloud_b)
    conditions = [
        _sign(t.tenkan, t.kijun),
        _sign(t.close, t.past_close),
        1 if t.close > top else (-1 if t.close < bottom else 0),
    ]
    if all(c == 1 for c in conditions):
        return Signal("三役好転", 1)
    if all(c == -1 for c in conditions):
        return Signal("三役逆転", -1)
    bullish = sum(1 for c in conditions if c == 1)
    return Signal(f"なし（強気 {bullish}/3）", 0)


def ma_order_signal(t: Technicals, config: ScoringConfig) -> Signal:
    """移動平均の並び。短い線ほど上なら上昇の並び、短い線ほど下なら下降の並び"""
    periods = sorted(t.sma)
    available = [(p, t.sma[p]) for p in periods if t.sma[p] is not None]
    missing = [p for p in periods if t.sma[p] is None]
    note = f"（{'・'.join(map(str, missing))}本は{NOT_AVAILABLE}）" if missing else ""

    if len(available) < 2 or (missing and not config.moving_average.allow_partial):
        return Signal(f"{NOT_AVAILABLE}{note}", 0)

    order = " > ".join(str(p) for p, _ in sorted(available, key=lambda pv: pv[1], reverse=True))
    values = [v for _, v in available]
    if all(a > b for a, b in pairwise(values)):
        return Signal(f"上昇の並び（{order}）{note}", 1)
    if all(a < b for a, b in pairwise(values)):
        return Signal(f"下降の並び（{order}）{note}", -1)
    return Signal(f"混在（{order}）{note}", 0)


def rsi_zone(value: float, config: ScoringConfig) -> tuple[str, str]:
    """RSI の区分を (キー, 表示名) で返す"""
    c = config.rsi
    if value <= c.oversold:
        return "oversold", "売られすぎ"
    if value < c.weak:
        return "weak", "弱め"
    if value <= c.strong:
        return "neutral", "中立"
    if value < c.overbought:
        return "strong", "強め"
    return "overbought", "買われすぎ"


def rsi_signal(t: Technicals, config: ScoringConfig) -> Signal:
    if t.rsi is None:
        return Signal(NOT_AVAILABLE, 0)
    key, label = rsi_zone(t.rsi, config)
    return Signal(f"{t.rsi:.1f}（{label}）", getattr(config.rsi.scores, key))


def macd_signal(t: Technicals) -> Signal:
    if t.macd_line is None or t.macd_signal is None:
        return Signal(NOT_AVAILABLE, 0)
    direction = _sign(t.macd_line, t.macd_signal)
    label = {1: "シグナルの上", -1: "シグナルの下", 0: "シグナルと同値"}[direction]
    zero = "0より上" if t.macd_line > 0 else "0より下" if t.macd_line < 0 else "0"
    return Signal(f"{label}・{zero}", direction)


def bb_label(t: Technicals) -> str:
    return NOT_AVAILABLE if t.bb_sigma is None else f"{t.bb_sigma:+.2f}σ"


def verdict(total: int, config: ScoringConfig) -> str:
    if total >= config.judgement.bullish_at:
        return "強気"
    if total <= config.judgement.bearish_at:
        return "弱気"
    return "中立"


def assess(t: Technicals, config: ScoringConfig) -> Assessment:
    signals = {
        "cloud": cloud_signal(t),
        "sanyaku": sanyaku_signal(t),
        "ma_order": ma_order_signal(t, config),
        "rsi": rsi_signal(t, config),
        "macd": macd_signal(t),
    }
    total = sum(s.score for s in signals.values())
    return Assessment(
        timeframe=t.timeframe,
        bb=bb_label(t),
        total=total,
        verdict=verdict(total, config),
        technicals=t,
        **signals,
    )
