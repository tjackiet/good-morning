"""RSS フィード取得モジュール（取得I/Oのみ。選定ロジックは good_morning.selector 参照）"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import httpx
import yaml

from good_morning.models import Article, FeedConfig, FeedsConfig
from good_morning.paths import CONFIG_DIR

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def load_feeds_config(config_path: Path | None = None) -> FeedsConfig:
    """フィード設定をYAMLから読み込む"""
    if config_path is None:
        config_path = CONFIG_DIR / "feeds.yaml"

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return FeedsConfig(**data)


def parse_published_date(entry: dict) -> datetime | None:
    """RSSエントリから公開日時をパース

    feedparser の published_parsed / updated_parsed は UTC に正規化された
    time.struct_time を返す。UTCとして解釈してからJSTに変換する。
    """
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=UTC).astimezone(JST)
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:6], tzinfo=UTC).astimezone(JST)
    return None


def fetch_feed(feed_config: FeedConfig) -> list[Article]:
    """単一のRSSフィードから記事を取得"""
    articles = []

    # User-Agentを設定してRSSを取得（一部サイトはブロック対策が必要）
    headers = {"User-Agent": USER_AGENT}
    response = httpx.get(feed_config.url, headers=headers, follow_redirects=True, timeout=30)
    response.raise_for_status()
    parsed = feedparser.parse(response.text)

    for entry in parsed.entries:
        published = parse_published_date(entry)
        summary = entry.get("summary", "") or entry.get("description", "")

        article = Article(
            title=entry.get("title", "No Title"),
            url=entry.get("link", ""),
            source=feed_config.name,
            category=feed_config.category,
            published=published,
            summary=summary[:500] if summary else None,  # 長すぎる場合は切り詰め
        )
        articles.append(article)

    return articles


def fetch_all_feeds(config_path: Path | None = None) -> list[Article]:
    """全フィードから記事を取得"""
    config = load_feeds_config(config_path)
    all_articles = []

    for feed_config in config.feeds:
        if not feed_config.enabled:
            continue

        try:
            articles = fetch_feed(feed_config)
            all_articles.extend(articles)
            logger.info("✓ %s: %d件取得", feed_config.name, len(articles))
        except Exception as e:  # noqa: BLE001 - 1フィードの失敗で全体を止めない（大原則3）
            logger.warning("✗ %s: 取得失敗 - %s", feed_config.name, e)

    return all_articles
