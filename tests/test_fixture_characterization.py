"""実フィードスナップショット(tests/fixtures/rss/)に対する現状挙動の固定テスト

2026-11-17 に各フィードから取得した実データ。ここでの数値は「現状」であり、正しさの保証では
ない。キーワードやフィードの設定を調整した際に、意図した差分だけが出ていることを確認するための
ベースライン。

keyword_pass は日付フィルタをかけない全件に対する filter_by_keywords の通過数（時刻に依存
しないようにするため）。実装本体（good_morning.selector.filters）と実際の config/feeds.yaml・
config/keywords.yaml をそのまま使うことで、このテスト自体が独自に判定ロジックを再実装して
現行実装と乖離するのを防ぐ。
"""

import feedparser
import pytest

from good_morning.collector.rss import parse_published_date
from good_morning.models import Article
from good_morning.selector.core import keyword_filter_exempt_sources, keyword_ignore_by_source
from good_morning.selector.filters import filter_by_keywords

# (feeds.yaml上の情報源名, フィクスチャファイル名, 取得件数, 日付パース成功件数, 通過件数)
BASELINE = [
    # 暗号資産の専門媒体はキーワードフィルタ免除（keyword_filter: false）なので全件通過
    ("CoinDesk", "coindesk.xml", 25, 25, 25),
    ("CoinPost", "coinpost.xml", 16, 16, 16),
    ("The Block", "theblock.xml", 20, 20, 20),
    # Bloomberg は一般の市場ニュースなので、金融政策・暗号資産などの語で絞り込む。
    # ウォッチリスト（見本）の会社名で Nvidia の記事も通る（Markets +2・Economics +1。会社名がなければ 4・9）
    ("Bloomberg（Markets）", "bloomberg_markets.xml", 20, 20, 6),
    ("Bloomberg（Economics）", "bloomberg_economics.xml", 20, 20, 10),
    ("FRB（金融政策）", "frb_monetary.xml", 15, 15, 15),
    # ignore_keywords: [日銀] で、統計の公表などが「日銀」の語だけで通るのを防いでいる（無視しないと14件）
    ("日本銀行（新着情報）", "boj_whatsnew.xml", 70, 70, 10),
    # ignore_keywords: [SEC] で、全記事が「SEC」の語で素通しになるのを防いでいる（無視しないと25件）
    ("SEC（プレスリリース）", "sec_press.xml", 25, 25, 5),
]


def _parse_fixture(fixtures_dir, filename: str, source: str) -> tuple[list[Article], list]:
    text = (fixtures_dir / "rss" / filename).read_text(encoding="utf-8")
    parsed = feedparser.parse(text)

    articles = []
    for entry in parsed.entries:
        summary = (entry.get("summary", "") or entry.get("description", ""))[:500]
        articles.append(
            Article(
                title=entry.get("title", "No Title"),
                url=entry.get("link", ""),
                source=source,
                category="crypto",
                summary=summary or None,
            )
        )
    return articles, parsed.entries


@pytest.mark.parametrize("source,filename,fetched,dated,keyword_pass", BASELINE)
def test_fixture_baseline(fixtures_dir, source, filename, fetched, dated, keyword_pass):
    articles, entries = _parse_fixture(fixtures_dir, filename, source)

    assert len(entries) == fetched
    assert sum(1 for e in entries if parse_published_date(e) is not None) == dated

    passed = filter_by_keywords(
        articles,
        exempt_sources=keyword_filter_exempt_sources(),
        ignore_by_source=keyword_ignore_by_source(),
    )
    assert len(passed) == keyword_pass


def test_baseline_covers_every_enabled_feed():
    """有効なフィードを足したら、このベースラインにも固定データを足す"""
    from good_morning.collector.rss import load_feeds_config

    enabled = {f.name for f in load_feeds_config().feeds if f.enabled}
    assert enabled == {source for source, *_ in BASELINE}
