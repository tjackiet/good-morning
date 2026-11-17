"""「主要ニュース」セクションのテスト（実フィードの fixtures。Claude には接続しない）"""

from datetime import datetime

import feedparser
import pytest

from good_morning.collector.rss import load_feeds_config, parse_published_date
from good_morning.context import RunContext
from good_morning.models import Article
from good_morning.news.builder import build_news, plain_text, snippet
from good_morning.processor.summarizer import SummarizerUnavailable
from good_morning.timeutil import JST

# 固定データを取った時刻（2026-11-17 23:40 JST ごろ）を「今」として扱う
NOW = datetime(2026, 11, 17, 23, 40, tzinfo=JST)


@pytest.fixture
def real_feeds(fixtures_dir, monkeypatch):
    """fetch_all_feeds を、実フィードの固定データから Article を返す偽物に差し替える"""
    slugs = {
        "CoinDesk": "coindesk", "CoinPost": "coinpost", "The Block": "theblock",
        "Bloomberg（Markets）": "bloomberg_markets", "Bloomberg（Economics）": "bloomberg_economics",
        "FRB（金融政策）": "frb_monetary", "日本銀行（新着情報）": "boj_whatsnew",
        "SEC（プレスリリース）": "sec_press",
    }  # fmt: skip

    def fake_fetch_all_feeds():
        articles = []
        for feed in load_feeds_config().feeds:
            if not feed.enabled:
                continue
            text = (fixtures_dir / "rss" / f"{slugs[feed.name]}.xml").read_text(encoding="utf-8")
            for e in feedparser.parse(text).entries:
                summary = e.get("summary", "") or e.get("description", "")
                articles.append(
                    Article(
                        title=e.get("title", "No Title"),
                        url=e.get("link", ""),
                        source=feed.name,
                        category=feed.category,
                        published=parse_published_date(e),
                        summary=summary[:500] or None,
                    )
                )
        return articles

    monkeypatch.setattr("good_morning.selector.core.fetch_all_feeds", fake_fetch_all_feeds)
    # 直近24時間の判定を固定データの時刻に合わせる
    monkeypatch.setattr("good_morning.selector.filters.datetime", _FrozenDatetime)
    monkeypatch.setattr("good_morning.selector.scoring.datetime", _FrozenDatetime)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW


def _fake_summarize(articles, client=None):
    for a in articles:
        a.ai_summary = f"{a.title[:10]} の要約"
        a.crypto_implication = "示唆"
    return articles


def test_news_section_with_summaries(real_feeds, monkeypatch):
    monkeypatch.setattr("good_morning.processor.summarizer.summarize_articles", _fake_summarize)
    ctx = RunContext(now=NOW)

    content = build_news(ctx)
    headings = [line for line in content.body.splitlines() if line.startswith("### ")]

    assert len(headings) == 5  # feeds.yaml の配分の合計
    assert headings[0].startswith("### 1. [")
    assert content.body.count("> **暗号資産への示唆**: 示唆") == 5
    assert " | 暗号資産 | 11/17（火）" in content.body
    assert content.sources[-1] == "Claude（ニュースの要約）"
    assert content.sources[0].startswith("RSS（")
    assert len(ctx.data["news"]) == 5


def test_news_section_without_api_key_shows_feed_summaries(real_feeds, monkeypatch):
    def unavailable(articles, client=None):
        raise SummarizerUnavailable("ANTHROPIC_API_KEY が設定されていないため、要約できません")

    monkeypatch.setattr("good_morning.processor.summarizer.summarize_articles", unavailable)

    content = build_news(RunContext(now=NOW))

    assert "（配信元の概要）" in content.body
    assert "<p>" not in content.body  # HTML タグは取り除く
    assert "⚠ 要約できませんでした: ANTHROPIC_API_KEY" in content.body
    assert all("Claude" not in s for s in content.sources)


def test_news_section_when_no_recent_articles(monkeypatch):
    monkeypatch.setattr("good_morning.news.builder.collect", lambda days: [])

    content = build_news(RunContext(now=NOW))

    assert content.body == "直近24時間に該当する記事はありませんでした。"


def test_plain_text_and_snippet():
    assert plain_text("<p>ビットコイン&amp;ETF</p>\n <b>上昇</b>") == "ビットコイン&ETF 上昇"
    assert snippet("あ" * 200, 10) == "あ" * 9 + "…"
