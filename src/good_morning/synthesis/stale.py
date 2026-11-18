"""前の営業日の終値（最新日の終値が取得元に未反映の銘柄）を使った文に、日付を添える

Claude には「未反映」の銘柄の値を使うときは日付を添えるよう指示しているが、落とすことがある
（2026-11-18、「NVDA -4.12% と大幅下落」と 11/16 の終値を日付なしで書いた）。そこで、
まとめの各文（3行の要約・強気材料・弱気材料など1項目ずつ）を機械的に確かめ、未反映の銘柄の
数値が出てくるのに日付がない文の末尾に「（NVDA は 11/16 終値）」を足す。

数値の照合（numbers.py）と同じく数字の並びで見るので、同じ数字が別の場所にあると
取り違えることがある（日付を添えすぎる側に倒れる）。
"""

import logging
from dataclasses import dataclass
from datetime import date

from good_morning.context import RunContext
from good_morning.markets.quotes import Quote
from good_morning.markets.tables import format_change, format_change_pct, format_value
from good_morning.synthesis.numbers import numbers_in, numbers_in_order

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaleValue:
    label: str  # 日付を添えるときの名前（株は銘柄コード、指数・セクターは名前）
    close_date: date  # 使った終値の日付（前の営業日）
    numbers: frozenset[str]  # 照合に使う数値（正規化済み）: 終値・前日比%（なければ前日比）


def _stale_value(q: Quote, label: str) -> StaleValue:
    texts = [format_value(q)]
    pct = format_change_pct(q)
    texts.append(pct if pct != "—" else format_change(q))  # 利回りは前日比%がないので前日比（bp）
    numbers = frozenset(n for text in texts for n in numbers_in(text))
    return StaleValue(label=label, close_date=q.last_date, numbers=numbers)


def stale_values(ctx: RunContext) -> list[StaleValue]:
    """マーケット一覧・セクター・株式ウォッチリストのうち、最新日の終値が未反映の銘柄"""
    values = []
    for key in ("markets", "sectors"):
        values.extend(
            _stale_value(q, q.name)
            for q in ctx.data.get(key) or []
            if isinstance(q, Quote) and q.missing_close is not None
        )
    values.extend(
        _stale_value(q, q.ticker)
        for q in ctx.data.get("stock_watchlist") or []
        if isinstance(q, Quote) and q.missing_close is not None
    )
    return values


def _has_date(text: str, day: date) -> bool:
    return f"{day.month}/{day.day}" in text or f"{day.month}月{day.day}日" in text


def annotate_stale_dates(text: str, values: list[StaleValue]) -> str:
    """未反映の銘柄の数値が出てくるのに日付がない文に、末尾で日付を添える"""
    hits: list[StaleValue] = []
    for number in numbers_in_order(text):  # 文に出てきた順に並べる
        for v in values:
            if number in v.numbers and v not in hits and not _has_date(text, v.close_date):
                hits.append(v)
    if not hits:
        return text
    by_date: dict[date, list[str]] = {}
    for v in hits:
        labels = by_date.setdefault(v.close_date, [])
        if v.label not in labels:
            labels.append(v.label)
    note = "（" + "、".join(
        f"{'・'.join(labels)} は {day.month}/{day.day} 終値" for day, labels in by_date.items()
    ) + "）"
    if text.endswith("。"):
        return text[:-1] + note + "。"
    return text + note
