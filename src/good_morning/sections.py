"""レポートの各セクションを組み立てる

セクションの並びは指示書「5. レポートの骨子」に合わせる。各セクションは
builder 関数で作り、builder が例外を投げても「取得失敗」として扱って次へ進む
（失敗理由はログに残す）。builder が未設定のセクションは「未実装」と表示する。
フェーズを進めるごとに SECTION_SPECS の builder を埋めていく。
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from good_morning.context import RunContext, SectionContent
from good_morning.crypto.builders import build_btc, build_crypto_watchlist
from good_morning.markets.builders import build_markets, build_sectors, build_stock_watchlist
from good_morning.reporter.markdown import STATUS_FAILED, STATUS_OK, STATUS_PENDING, Section
from good_morning.schedule.builder import build_calendar

__all__ = [
    "SECTION_SPECS",
    "RunContext",
    "SectionContent",
    "SectionSpec",
    "build_section",
    "build_sections",
]

logger = logging.getLogger(__name__)

STATUS_LABELS = {STATUS_OK: "OK", STATUS_FAILED: "取得失敗", STATUS_PENDING: "未実装"}


SectionBuilder = Callable[[RunContext], SectionContent]


@dataclass
class SectionSpec:
    key: str
    title: str
    phase: int
    builder: SectionBuilder | None = None


SECTION_SPECS: list[SectionSpec] = [
    SectionSpec("summary", "今朝のまとめ", phase=5),
    SectionSpec("markets", "マーケット一覧", phase=1, builder=build_markets),
    SectionSpec("sectors", "セクター別騰落率", phase=1, builder=build_sectors),
    SectionSpec("btc", "BTCの詳細", phase=2, builder=build_btc),
    SectionSpec("crypto_watchlist", "暗号資産ウォッチリスト", phase=2, builder=build_crypto_watchlist),
    SectionSpec("stock_watchlist", "株式ウォッチリスト", phase=1, builder=build_stock_watchlist),
    SectionSpec("calendar", "今後の予定", phase=3, builder=build_calendar),
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
