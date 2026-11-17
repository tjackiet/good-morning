"""good_morning.selector.core のテスト"""

from datetime import timedelta

from good_morning.selector.core import (
    collect,
    explain_selection,
    keyword_filter_exempt_sources,
    keyword_ignore_by_source,
)

EXEMPT = "good_morning.selector.core.keyword_filter_exempt_sources"
FETCH = "good_morning.selector.core.fetch_all_feeds"


def test_collect_applies_date_then_keyword_filter(make_article, monkeypatch):
    recent_market = make_article(title="ビットコインが反発", published_offset=timedelta(hours=-1))
    recent_other = make_article(title="今日の天気", published_offset=timedelta(hours=-1))
    old_market = make_article(title="日銀が利上げ", published_offset=timedelta(days=-2))
    monkeypatch.setattr(FETCH, lambda: [recent_market, recent_other, old_market])

    assert collect(days=1) == [recent_market]


def test_collect_skips_keyword_filter_when_disabled(make_article, monkeypatch):
    recent_other = make_article(title="今日の天気", published_offset=timedelta(hours=-1))
    monkeypatch.setattr(FETCH, lambda: [recent_other])

    assert collect(days=1, keyword_filter=False) == [recent_other]


def test_collect_returns_articles_in_score_order(make_article, monkeypatch):
    weak = make_article(title="ドル円が小動き", published_offset=timedelta(hours=-1))
    strong = make_article(title="FOMC後にビットコインETFへ資金流入", published_offset=timedelta(hours=-1))
    monkeypatch.setattr(FETCH, lambda: [weak, strong])

    assert collect(days=1) == [strong, weak]
    assert strong.score > weak.score > 0


def test_keyword_filter_settings_read_feeds_yaml(tmp_path):
    config = tmp_path / "feeds.yaml"
    config.write_text(
        "feeds:\n"
        '  - name: "免除フィード"\n'
        '    url: "https://example.com/a.xml"\n'
        '    category: "crypto"\n'
        "    keyword_filter: false\n"
        '  - name: "通常フィード"\n'
        '    url: "https://example.com/b.xml"\n'
        '    category: "official"\n'
        "    ignore_keywords: [SEC]\n",
        encoding="utf-8",
    )

    assert keyword_filter_exempt_sources(config) == frozenset({"免除フィード"})
    assert keyword_ignore_by_source(config) == {"通常フィード": frozenset({"SEC"})}


def test_shipped_feeds_yaml_settings():
    """出荷時の免除・無視の設定を固定する（増減したときにレビューで気づけるように）"""
    assert keyword_filter_exempt_sources() == frozenset(
        {"CoinDesk", "CoinPost", "The Block", "FRB（金融政策）"}
    )
    assert keyword_ignore_by_source() == {
        "日本銀行（新着情報）": frozenset({"日銀"}),
        "SEC（プレスリリース）": frozenset({"SEC"}),
    }


def test_collect_exempts_configured_sources_from_keyword_filter(make_article, monkeypatch):
    exempt_off_topic = make_article(
        title="Grvt launches RWA perpetuals", source="CoinDesk", published_offset=timedelta(hours=-1)
    )
    other_off_topic = make_article(
        title="今日の天気", source="Bloomberg（Markets）", published_offset=timedelta(hours=-1)
    )
    monkeypatch.setattr(FETCH, lambda: [exempt_off_topic, other_off_topic])
    monkeypatch.setattr(EXEMPT, lambda: frozenset({"CoinDesk"}))

    assert collect(days=1) == [exempt_off_topic]


def test_collect_drops_articles_matching_only_ignored_keywords(make_article, monkeypatch):
    sec_only = make_article(
        title="SEC Proposes Disclosure Reforms",
        source="SEC（プレスリリース）",
        published_offset=timedelta(hours=-1),
    )
    sec_crypto = make_article(
        title="SEC Approves Bitcoin ETF",
        source="SEC（プレスリリース）",
        published_offset=timedelta(hours=-1),
    )
    monkeypatch.setattr(FETCH, lambda: [sec_only, sec_crypto])

    assert collect(days=1) == [sec_crypto]


def test_collect_still_applies_date_filter_to_exempt_sources(make_article, monkeypatch):
    old = make_article(title="Grvt launches", source="CoinDesk", published_offset=timedelta(days=-2))
    monkeypatch.setattr(FETCH, lambda: [old])
    monkeypatch.setattr(EXEMPT, lambda: frozenset({"CoinDesk"}))

    assert collect(days=1) == []


def test_explain_selection_marks_exempt_articles_as_passed(make_article, monkeypatch):
    exempt_off_topic = make_article(
        title="Grvt launches", source="CoinDesk", published_offset=timedelta(hours=-1)
    )
    monkeypatch.setattr(FETCH, lambda: [exempt_off_topic])
    monkeypatch.setattr(EXEMPT, lambda: frozenset({"CoinDesk"}))

    explain_selection(days=1)

    assert exempt_off_topic.excluded_reason is None
    assert exempt_off_topic.matched_keywords == []


def test_explain_selection_assigns_reasons_per_stage(make_article, monkeypatch):
    passed = make_article(title="ビットコインが反発", published_offset=timedelta(hours=-1))
    no_date = make_article(title="ビットコインが反発", published_offset=None)
    too_old = make_article(title="ビットコインが反発", published_offset=timedelta(days=-2))
    no_keyword = make_article(title="今日の天気", published_offset=timedelta(hours=-1))
    monkeypatch.setattr(FETCH, lambda: [passed, no_date, too_old, no_keyword])

    result = explain_selection(days=1)

    assert passed.excluded_reason is None
    assert passed.matched_keywords == ["ビットコイン"]
    assert no_date.excluded_reason == "日付なし"
    assert too_old.excluded_reason == "直近1日外"
    assert no_keyword.excluded_reason == "キーワード不一致"
    assert result == [passed, no_date, too_old, no_keyword]
