"""記事選定のオーケストレーション"""

import logging
from pathlib import Path

from good_morning.collector import fetch_all_feeds, load_feeds_config
from good_morning.models import Article
from good_morning.selector.filters import (
    count_undated_by_source,
    filter_by_keywords,
    filter_recent_articles,
    matched_keywords_in_article,
)
from good_morning.selector.ranking import rank_articles
from good_morning.selector.scoring import score_articles

logger = logging.getLogger(__name__)

REASON_NO_DATE = "日付なし"
REASON_NO_KEYWORD = "キーワード不一致"


def keyword_filter_exempt_sources(config_path: Path | None = None) -> frozenset[str]:
    """キーワードフィルタを適用しない情報源名の集合を feeds.yaml から得る

    feeds.yaml の keyword_filter: false が付いたフィードが対象。
    """
    config = load_feeds_config(config_path)
    return frozenset(feed.name for feed in config.feeds if not feed.keyword_filter)


def keyword_ignore_by_source(config_path: Path | None = None) -> dict[str, frozenset[str]]:
    """フィードごとに数えないキーワード（feeds.yaml の ignore_keywords）"""
    config = load_feeds_config(config_path)
    return {feed.name: frozenset(feed.ignore_keywords) for feed in config.feeds if feed.ignore_keywords}


def collect(days: int = 1, keyword_filter: bool = True) -> list[Article]:
    """メイン収集関数: フィード取得 + フィルタリング"""
    logger.info("RSSフィードを取得中...")
    articles = fetch_all_feeds()
    logger.info("合計 %d 件の記事を取得", len(articles))

    undated = count_undated_by_source(articles)
    if undated:
        detail = ", ".join(f"{source} {count}件" for source, count in undated.items())
        logger.warning("⚠ 公開日時を取得できず除外: %d 件（%s）", sum(undated.values()), detail)

    filtered = filter_recent_articles(articles, days=days)
    logger.info("直近%d日間の記事: %d 件", days, len(filtered))

    exempt = keyword_filter_exempt_sources()
    ignore = keyword_ignore_by_source()

    if keyword_filter:
        filtered = filter_by_keywords(filtered, exempt_sources=exempt, ignore_by_source=ignore)
        detail = f"（{', '.join(sorted(exempt))} はキーワードフィルタ免除）" if exempt else ""
        logger.info("キーワード一致: %d 件%s", len(filtered), detail)

    score_articles(filtered, exempt_sources=exempt, ignore_by_source=ignore)
    return rank_articles(filtered)


def explain_selection(days: int = 1) -> list[Article]:
    """全記事に通過/除外理由とマッチキーワードを付与して返す（--explain 用）

    collect() が使うフィルタ関数をそのまま再利用し、除外された記事も
    破棄せず matched_keywords / excluded_reason を付けて返す。
    """
    articles = fetch_all_feeds()
    recent_ids = {id(a) for a in filter_recent_articles(articles, days=days)}
    exempt = keyword_filter_exempt_sources()
    ignore = keyword_ignore_by_source()
    score_articles(articles, exempt_sources=exempt, ignore_by_source=ignore)

    for article in articles:
        article.matched_keywords = matched_keywords_in_article(
            article, ignore.get(article.source, frozenset())
        )

        if article.published is None:
            article.excluded_reason = REASON_NO_DATE
        elif id(article) not in recent_ids:
            article.excluded_reason = f"直近{days}日外"
        elif not article.matched_keywords and article.source not in exempt:
            article.excluded_reason = REASON_NO_KEYWORD
        else:
            article.excluded_reason = None

    return articles
