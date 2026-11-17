"""good_morning.selector.scoring のテスト（重みは config/keywords.yaml の weight）"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from good_morning.selector.keywords import KEYWORD_WEIGHTS, load_keyword_config
from good_morning.selector.scoring import (
    EXEMPT_SOURCE_BASE_POINTS,
    RECENCY_MAX_POINTS,
    TITLE_MULTIPLIER,
    keyword_score,
    keyword_weight,
    recency_score,
    score_article,
    score_articles,
)

JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=JST)


def test_weights_come_from_yaml():
    assert KEYWORD_WEIGHTS["暗号資産"] == 3.0
    assert KEYWORD_WEIGHTS["金利・為替"] == 2.0
    assert keyword_weight("ビットコイン") == 3.0
    assert keyword_weight("ドル円") == 2.0


def test_keyword_weight_falls_back_for_unknown_keyword():
    assert keyword_weight("存在しないキーワード") == 1.0


def test_old_list_format_is_still_readable(tmp_path):
    """aion の形式（カテゴリ: [語, ...]）も読める。重みは既定の 1.0"""
    path = tmp_path / "keywords.yaml"
    path.write_text("keywords:\n  基本:\n    - AI\n", encoding="utf-8")

    assert load_keyword_config(path) == {"基本": (1.0, ["AI"])}


def test_keyword_score_counts_title_matches_more_than_summary(make_article):
    in_title = make_article(title="ビットコインが反発", summary="詳細は後日")
    in_summary = make_article(title="相場の話", summary="ビットコインが反発した")

    assert keyword_score(in_title) == keyword_weight("ビットコイン") * TITLE_MULTIPLIER
    assert keyword_score(in_summary) == keyword_weight("ビットコイン")


def test_keyword_score_does_not_double_count_same_keyword(make_article):
    both = make_article(title="ビットコインが反発", summary="ビットコインの値動き")

    assert keyword_score(both) == keyword_weight("ビットコイン") * TITLE_MULTIPLIER


def test_keyword_score_accumulates_over_distinct_keywords(make_article):
    one = make_article(title="ビットコインが反発")
    two = make_article(title="FOMC後にビットコインが反発")

    assert keyword_score(two) > keyword_score(one)


def test_keyword_score_ignores_given_keywords(make_article):
    article = make_article(title="SEC Approves Bitcoin ETF")

    assert keyword_score(article, frozenset({"SEC"})) < keyword_score(article)


def test_keyword_score_is_zero_without_matches(make_article):
    assert keyword_score(make_article(title="今日の天気", summary="全国的に晴れ")) == 0.0


def test_recency_score_decays_with_age(make_article):
    fresh = make_article(title="x")
    fresh.published = NOW
    day_old = make_article(title="x")
    day_old.published = NOW - timedelta(hours=24)

    assert recency_score(fresh, now=NOW) == RECENCY_MAX_POINTS
    assert recency_score(day_old, now=NOW) == RECENCY_MAX_POINTS / 2  # 半減期は24時間


def test_recency_score_is_zero_without_published_date(make_article):
    assert recency_score(make_article(title="x", published_offset=None)) == 0.0


def test_recency_score_clamps_future_dates(make_article):
    future = make_article(title="x")
    future.published = NOW + timedelta(hours=5)

    assert recency_score(future, now=NOW) == RECENCY_MAX_POINTS


def test_score_article_gives_base_points_to_exempt_sources(make_article):
    """免除フィードはマッチ0件がありうるので、スコア0で常に沈まないこと"""
    article = make_article(title="Grvt launches RWA perpetuals", source="CoinDesk")
    article.published = NOW

    without = score_article(article, now=NOW)
    with_exemption = score_article(article, exempt_sources=frozenset({"CoinDesk"}), now=NOW)

    assert with_exemption - without == EXEMPT_SOURCE_BASE_POINTS


def test_score_articles_assigns_score_field(make_article):
    market = make_article(title="日銀が利上げを決定")
    market.published = NOW
    other = make_article(title="今日の天気")
    other.published = NOW

    score_articles([market, other], now=NOW)

    assert market.score > other.score
    assert other.score == RECENCY_MAX_POINTS  # キーワード0件でも新しさ分は付く
