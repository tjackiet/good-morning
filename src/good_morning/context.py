"""セクションの builder が受け取る・返す型

good_morning.sections（並びと失敗の扱い）と各 builder の実装の間で共有するため、
循環 import にならないよう別のモジュールに置く。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from good_morning.watchlist import Watchlist


@dataclass
class RunContext:
    """1回の実行で各 builder が共有する情報"""

    now: datetime
    watchlist: Watchlist | None = None
    # builder が計算済みの数値を置く場所（フェーズ5で「今朝のまとめ」の根拠に使う）
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SectionContent:
    """builder の戻り値"""

    body: str
    basis: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
