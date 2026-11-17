"""レポートの各セクションを組み立てる

セクションの並びは指示書「5. レポートの骨子」に合わせる。各セクションは
builder 関数で作り、builder が例外を投げても「取得失敗」として扱って次へ進む
（失敗理由はログに残す）。builder が未設定のセクションは「未実装」と表示する。
フェーズを進めるごとに SECTION_SPECS の builder を埋めていく。
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from good_morning.reporter.markdown import STATUS_FAILED, STATUS_OK, STATUS_PENDING, Section
from good_morning.watchlist import Watchlist

logger = logging.getLogger(__name__)

STATUS_LABELS = {STATUS_OK: "OK", STATUS_FAILED: "取得失敗", STATUS_PENDING: "未実装"}


@dataclass
class RunContext:
    """1回の実行で各 builder が共有する情報"""

    now: datetime
    watchlist: Watchlist | None = None


@dataclass
class SectionContent:
    """builder の戻り値"""

    body: str
    basis: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


SectionBuilder = Callable[[RunContext], SectionContent]


@dataclass
class SectionSpec:
    key: str
    title: str
    phase: int
    builder: SectionBuilder | None = None


SECTION_SPECS: list[SectionSpec] = [
    SectionSpec("summary", "今朝のまとめ", phase=5),
    SectionSpec("markets", "マーケット一覧", phase=1),
    SectionSpec("sectors", "セクター別騰落率", phase=1),
    SectionSpec("btc", "BTCの詳細", phase=2),
    SectionSpec("crypto_watchlist", "暗号資産ウォッチリスト", phase=2),
    SectionSpec("stock_watchlist", "株式ウォッチリスト", phase=1),
    SectionSpec("calendar", "今後の予定", phase=3),
    SectionSpec("news", "主要ニュース", phase=4),
    SectionSpec("crypto_implications", "暗号資産への示唆", phase=5),
]


def build_section(spec: SectionSpec, ctx: RunContext) -> Section:
    """1セクションを作る。builder の例外はここで止め、取得失敗として返す"""
    if spec.builder is None:
        return Section(
            key=spec.key,
            title=spec.title,
            status=STATUS_PENDING,
            note=f"フェーズ{spec.phase}で実装予定",
        )

    try:
        content = spec.builder(ctx)
    except Exception:
        logger.exception("セクション「%s」の作成に失敗しました", spec.title)
        return Section(key=spec.key, title=spec.title, status=STATUS_FAILED)

    return Section(
        key=spec.key,
        title=spec.title,
        status=STATUS_OK,
        body=content.body,
        basis=content.basis,
        sources=content.sources,
    )


def build_sections(ctx: RunContext, specs: list[SectionSpec] | None = None) -> list[Section]:
    specs = SECTION_SPECS if specs is None else specs
    sections = []
    for spec in specs:
        section = build_section(spec, ctx)
        logger.info("  %s: %s", spec.title, STATUS_LABELS[section.status])
        sections.append(section)
    return sections
