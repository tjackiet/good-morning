"""good_morning.collector.rss のテスト（取得I/Oと日付パース）"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from good_morning.collector.rss import fetch_all_feeds, fetch_feed, parse_published_date
from good_morning.models import FeedConfig


def test_parse_published_date_treats_struct_time_as_utc():
    """feedparser の published_parsed はUTC正規化済み。JSTに変換されて+9時間になる。"""
    entry = SimpleNamespace(published_parsed=(2026, 11, 17, 3, 0, 0, 0, 0, 0))

    result = parse_published_date(entry)

    assert result == datetime(2026, 11, 17, 3, 0, 0, tzinfo=UTC).astimezone(result.tzinfo)
    assert result.hour == 12  # UTC 3:00 -> JST 12:00


def test_parse_published_date_falls_back_to_updated_parsed():
    entry = SimpleNamespace(published_parsed=None, updated_parsed=(2026, 11, 17, 3, 0, 0, 0, 0, 0))

    assert parse_published_date(entry).hour == 12


def test_parse_published_date_returns_none_when_no_dates():
    assert parse_published_date(SimpleNamespace(published_parsed=None, updated_parsed=None)) is None


def _fake_get(text):
    def fake_get(url, headers=None, follow_redirects=True, timeout=30):
        return SimpleNamespace(text=text, raise_for_status=lambda: None)

    return fake_get


def test_fetch_feed_parses_real_fixture(fixtures_dir, monkeypatch):
    """CoinPost の実フィード（2026-11-17 取得）を解析し、Article群を構築できる。"""
    xml_text = (fixtures_dir / "rss" / "coinpost.xml").read_text(encoding="utf-8")
    monkeypatch.setattr("good_morning.collector.rss.httpx.get", _fake_get(xml_text))

    feed_config = FeedConfig(name="CoinPost", url="https://example.com/rss", category="crypto")
    articles = fetch_feed(feed_config)

    assert len(articles) == 16
    assert all(a.source == "CoinPost" and a.category == "crypto" for a in articles)
    assert all(a.summary is None or len(a.summary) <= 500 for a in articles)
    assert all(a.published is not None for a in articles)


def test_fetch_feed_handles_html_page_gracefully(fixtures_dir, monkeypatch):
    """RSS の URL が HTML ページを返すようになった場合は0件になる（例外にはならない）。"""
    html_text = (fixtures_dir / "rss" / "html_page_instead_of_rss.html").read_text(encoding="utf-8")
    monkeypatch.setattr("good_morning.collector.rss.httpx.get", _fake_get(html_text))

    feed_config = FeedConfig(name="壊れたフィード", url="https://example.com/broken", category="macro")

    assert fetch_feed(feed_config) == []


def test_fetch_all_feeds_raises_when_every_feed_fails(tmp_path, monkeypatch):
    """全フィードが失敗したら「記事0件」と区別できるよう例外にする（セクションは取得失敗になる）"""
    config = tmp_path / "feeds.yaml"
    config.write_text(
        "feeds:\n  - {name: A, url: 'https://example.com/a', category: crypto}\n"
        "  - {name: B, url: 'https://example.com/b', category: macro}\n",
        encoding="utf-8",
    )

    def broken(url, **kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr("good_morning.collector.rss.httpx.get", broken)

    with pytest.raises(RuntimeError, match="すべてのフィード"):
        fetch_all_feeds(config)
