"""good_morning.selector.filters のテスト（市場ニュースのキーワード）"""

from datetime import timedelta

import pytest

from good_morning.selector.filters import (
    count_undated_by_source,
    filter_by_keywords,
    filter_recent_articles,
    matched_keywords_in_article,
)


def test_filter_recent_articles_keeps_only_within_window(make_article):
    recent = make_article(title="新しい記事", published_offset=timedelta(hours=-2))
    old = make_article(title="古い記事", published_offset=timedelta(days=-2))
    undated = make_article(title="日付なし記事", published_offset=None)

    result = filter_recent_articles([recent, old, undated], days=1)

    assert result == [recent]


def test_filter_recent_articles_boundary_is_inclusive(make_article):
    # ちょうど境界（1日前）は含まれる想定 (>= cutoff)
    boundary = make_article(title="境界記事", published_offset=timedelta(days=-1, seconds=1))

    assert filter_recent_articles([boundary], days=1) == [boundary]


def test_matched_keywords_true_positive(make_article):
    article = make_article(title="ビットコインETFに資金流入　FOMCを前に", summary=None)

    assert set(matched_keywords_in_article(article)) == {"FOMC", "ビットコイン", "ETF"}


@pytest.mark.parametrize(
    "title",
    [
        "NETFLIX shares jump after earnings",  # NETFLIX の中の ETF
        "Tech SECTOR leads gains",  # SECTOR の中の SEC
        "A SECOND wave of selling",  # SECOND の中の SEC
        "ETHICS review of the board",  # ETHICS の中の ETH
        "Federation of unions",  # Federation の中の Fed
    ],
)
def test_word_boundary_rejects_substring_false_positives(make_article, title):
    """英語の語は単語の境界で区切ってマッチする（部分文字列では誤爆しない）"""
    assert matched_keywords_in_article(make_article(title=title, summary=None)) == []


@pytest.mark.parametrize(
    "title,keyword",
    [
        ("Bitcoin ETFs see record inflows", "ETF"),
        ("Stablecoins gain traction in payments", "stablecoin"),
        ("New tariffs weigh on markets", "tariff"),
        ("Treasury yields climb", "yield"),
    ],
)
def test_english_plurals_match(make_article, title, keyword):
    """英語のフィードは複数形で書くことが多いので、s / es にもマッチする"""
    assert keyword in matched_keywords_in_article(make_article(title=title, summary=None))


def test_japanese_adjacent_keywords_still_match(make_article):
    """日本語に直接つながる英語の語もマッチする（日本語は単語の間に空白を入れないため）"""
    article = make_article(title="米SECがビットコイン現物ETFを承認", summary=None)

    assert {"SEC", "ビットコイン", "ETF"} <= set(matched_keywords_in_article(article))


def test_ignore_keywords_are_not_counted(make_article):
    """配信元の名前（SEC のプレスリリースの「SEC」）は数えない"""
    article = make_article(title="SEC Announces Enforcement Results", summary=None)

    assert matched_keywords_in_article(article) == ["SEC"]
    assert matched_keywords_in_article(article, frozenset({"SEC"})) == []


def test_matched_keywords_no_match(make_article):
    article = make_article(title="今日の天気について", summary="全国的に晴れ")

    assert matched_keywords_in_article(article) == []


def test_filter_by_keywords_excludes_articles_without_keywords(make_article):
    market = make_article(title="日銀が利上げを決定")
    other = make_article(title="今日の天気")

    assert filter_by_keywords([market, other]) == [market]


def test_filter_by_keywords_passes_everything_from_exempt_source(make_article):
    """免除フィードはキーワード0件でも通過する"""
    off_topic = make_article(title="Grvt launches RWA perpetuals", source="CoinDesk")

    assert filter_by_keywords([off_topic], exempt_sources=frozenset({"CoinDesk"})) == [off_topic]


def test_filter_by_keywords_still_filters_non_exempt_sources(make_article):
    exempt_off_topic = make_article(title="今日の天気", source="CoinDesk")
    other_off_topic = make_article(title="今日の天気", source="Bloomberg（Markets）")
    other_market = make_article(title="Fed signals rate hikes", source="Bloomberg（Markets）")

    result = filter_by_keywords(
        [exempt_off_topic, other_off_topic, other_market],
        exempt_sources=frozenset({"CoinDesk"}),
    )

    assert result == [exempt_off_topic, other_market]


def test_filter_by_keywords_applies_ignore_per_source(make_article):
    sec_only = make_article(title="SEC Proposes Disclosure Reforms", source="SEC（プレスリリース）")
    sec_crypto = make_article(title="SEC Approves Bitcoin ETF", source="SEC（プレスリリース）")
    elsewhere = make_article(title="SEC Proposes Disclosure Reforms", source="Bloomberg（Markets）")

    result = filter_by_keywords(
        [sec_only, sec_crypto, elsewhere],
        ignore_by_source={"SEC（プレスリリース）": frozenset({"SEC"})},
    )

    # 「SEC」だけの記事は SEC のフィードでは落ち、他のフィードでは通る
    assert result == [sec_crypto, elsewhere]


def test_filter_by_keywords_defaults_to_no_exemption(make_article):
    assert filter_by_keywords([make_article(title="今日の天気", source="CoinDesk")]) == []


def test_count_undated_by_source(make_article):
    a1 = make_article(source="CoinPost", published_offset=None)
    a2 = make_article(source="CoinPost", published_offset=None)
    a3 = make_article(source="CoinDesk", published_offset=timedelta(hours=-1))

    assert count_undated_by_source([a1, a2, a3]) == {"CoinPost": 2}
