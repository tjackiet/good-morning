"""「主要ニュース」のセクション

RSS を集めて（aion の仕組み）、キーワードとスコアで3〜5本を選び、Claude で
「要約」と「暗号資産への示唆」を付ける。Claude が使えないとき（API キーがない など）は、
配信元の概要（RSS の description）を短くして載せ、セクションは止めない（大原則3）。
"""

import html
import logging
import re

from good_morning.collector.rss import load_feeds_config
from good_morning.context import RunContext, SectionContent
from good_morning.models import Article
from good_morning.processor import summarizer
from good_morning.selector import collect, select_for_summary
from good_morning.selector.keywords import WATCHLIST_SETTINGS
from good_morning.selector.scoring import is_earnings_article
from good_morning.timeutil import format_jst, format_month_day

logger = logging.getLogger(__name__)

NEWS_DAYS = 1  # 直近24時間の記事から選ぶ
SNIPPET_CHARS = 140
SOURCE_CLAUDE = "Claude（ニュースの要約）"

_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


def plain_text(text: str | None) -> str:
    """RSS の概要から HTML タグを取り、空白をまとめる"""
    if not text:
        return ""
    return _SPACES.sub(" ", html.unescape(_TAG.sub(" ", text))).strip()


def snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_article(index: int, article: Article, labels: dict[str, str]) -> list[str]:
    label = labels.get(article.category, article.category)
    published = (
        f"{format_month_day(article.published)} {article.published:%H:%M}"
        if article.published
        else "日時不明"
    )
    lines = [
        f"### {index}. [{article.title}]({article.url})",
        "",
        f"{article.source} | {label} | {published}",
        "",
    ]
    if article.ai_summary:
        lines.extend([article.ai_summary, ""])
        if article.crypto_implication:
            lines.extend([f"> **暗号資産への示唆**: {article.crypto_implication}", ""])
    else:
        text = snippet(plain_text(article.summary))
        if text:
            lines.extend([f"（配信元の概要）{text}", ""])
    return lines


def build_news(ctx: RunContext) -> SectionContent:
    feeds = load_feeds_config()
    labels = {name: c.label for name, c in feeds.categories.items()}
    basis = [f"主要ニュース: 直近24時間の RSS（{format_jst(ctx.now)} 取得）"]

    articles = collect(days=NEWS_DAYS)
    if not articles:
        return SectionContent(body="直近24時間に該当する記事はありませんでした。", basis=basis)

    # ウォッチリストの企業の決算の記事を優先して1本（keywords.yaml の watchlist.earnings_slots）
    selected = select_for_summary(
        articles,
        priority=is_earnings_article,
        priority_slots=WATCHLIST_SETTINGS.earnings_slots,
    )
    ctx.data["news"] = selected

    notes = []
    try:
        summarizer.summarize_articles(selected)
    except summarizer.SummarizerUnavailable as e:
        logger.warning("主要ニュース: 要約できません - %s", e)
        notes.append(f"⚠ 要約できませんでした: {e} 配信元の概要を載せています。")
    if any(a.ai_summary for a in selected) and not all(a.ai_summary for a in selected):
        notes.append("⚠ 一部の記事は要約に失敗したため、配信元の概要を載せています（理由はログを参照）。")

    body: list[str] = []
    for i, article in enumerate(selected, 1):
        body.extend(render_article(i, article, labels))
    body.extend(notes)

    sources = []
    for article in selected:
        if article.source not in sources:
            sources.append(article.source)
    source_list = [f"RSS（{'・'.join(sources)}）"]
    if any(a.ai_summary for a in selected):
        source_list.append(SOURCE_CLAUDE)

    return SectionContent(body="\n".join(body).rstrip(), basis=basis, sources=source_list)
