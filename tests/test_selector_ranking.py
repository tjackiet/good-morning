"""good_morning.selector.ranking のテスト（配分は config/feeds.yaml の categories）"""

from datetime import timedelta

from good_morning.selector.ranking import (
    CATEGORY_QUOTA,
    DEFAULT_MAX_ARTICLES,
    allocate_quota,
    category_breakdown,
    rank_articles,
    select_for_summary,
)


def _scored(make_article, category: str, score: float, title: str):
    article = make_article(title=title, category=category, published_offset=timedelta(hours=-1))
    article.score = score
    return article


def test_quota_comes_from_feeds_yaml():
    """指示書: 主要ニュースは3〜5本。配分の合計（5）が既定の本数"""
    assert CATEGORY_QUOTA == {"crypto": 2, "macro": 2, "official": 1}
    assert DEFAULT_MAX_ARTICLES == 5


def test_rank_articles_sorts_by_score_descending(make_article):
    low = _scored(make_article, "crypto", 1.0, "低")
    high = _scored(make_article, "crypto", 9.0, "高")
    mid = _scored(make_article, "crypto", 5.0, "中")

    assert rank_articles([low, high, mid]) == [high, mid, low]


def test_rank_articles_does_not_mutate_input(make_article):
    original = [_scored(make_article, "crypto", 1.0, "低"), _scored(make_article, "crypto", 9.0, "高")]
    snapshot = list(original)

    rank_articles(original)

    assert original == snapshot


def test_rank_articles_breaks_ties_by_recency_then_title(make_article):
    older = _scored(make_article, "crypto", 5.0, "b")
    older.published = older.published - timedelta(hours=5)
    newer = _scored(make_article, "crypto", 5.0, "c")

    assert rank_articles([older, newer]) == [newer, older]


def test_allocate_quota_matches_default():
    assert allocate_quota(5) == {"crypto": 2, "macro": 2, "official": 1}


def test_allocate_quota_always_sums_to_max_articles():
    for max_articles in range(21):
        assert sum(allocate_quota(max_articles).values()) == max_articles, max_articles


def test_allocate_quota_scales_proportionally():
    assert allocate_quota(10) == {"crypto": 4, "macro": 4, "official": 2}


def test_allocate_quota_handles_zero():
    assert allocate_quota(0) == {"crypto": 0, "macro": 0, "official": 0}


def test_select_for_summary_enforces_category_quota(make_article):
    """1カテゴリが上位を独占していても、他カテゴリの枠が確保されること"""
    crypto = [_scored(make_article, "crypto", 100 - i, f"c{i}") for i in range(20)]
    macro = [_scored(make_article, "macro", 10 - i, f"m{i}") for i in range(20)]
    official = [_scored(make_article, "official", 5 - i, f"o{i}") for i in range(20)]

    selected = select_for_summary(crypto + macro + official)

    assert len(selected) == 5
    assert category_breakdown(selected) == {"crypto": 2, "macro": 2, "official": 1}


def test_select_for_summary_backfills_when_a_category_is_empty(make_article):
    """公的機関の記事が直近にない日は、余った枠を全体のスコア順で埋める"""
    crypto = [_scored(make_article, "crypto", 100 - i, f"c{i}") for i in range(20)]
    macro = [_scored(make_article, "macro", 50 - i, f"m{i}") for i in range(20)]

    selected = select_for_summary(crypto + macro)

    assert len(selected) == 5
    assert category_breakdown(selected) == {"crypto": 3, "macro": 2}


def test_select_for_summary_returns_fewer_than_max_when_pool_is_small(make_article):
    articles = [_scored(make_article, "crypto", 5.0, "c0")]

    assert select_for_summary(articles) == articles


def test_select_for_summary_handles_empty_pool():
    assert select_for_summary([]) == []


def test_select_for_summary_result_is_score_ordered(make_article):
    articles = [
        _scored(make_article, "crypto", 1.0, "c"),
        _scored(make_article, "macro", 9.0, "m"),
        _scored(make_article, "official", 5.0, "o"),
    ]

    assert [a.score for a in select_for_summary(articles)] == [9.0, 5.0, 1.0]


def test_category_breakdown_counts_per_category(make_article):
    articles = [
        _scored(make_article, "crypto", 1.0, "a"),
        _scored(make_article, "crypto", 1.0, "b"),
        _scored(make_article, "macro", 1.0, "c"),
    ]

    assert category_breakdown(articles) == {"crypto": 2, "macro": 1}
