"""記事スコアリング（構造的シグナルのみ）

ここで扱うのは「その記事がどれくらい対象分野の話であることが確からしいか」だけで、
記事の中身が良いか悪いか（ニュースバリュー）は判定しない。表明止まり記事の
減点のような価値判断は別途扱う。

スコアは以下の構造的シグナルの合計:

1. マッチしたキーワードの重み和
   固有名詞ほど「本当に対象分野の話である」ことの証拠として強い。
   例（aion から引き継いだ AI 向け語彙。フェーズ4で市場向けに入れ替える）:
   'AI' や 'ロボット' は文脈次第で何にでも付くが、'Anthropic' や 'DeepSeek' が
   出てくる記事は AI の話である確率が高い。重みは config/keywords.yaml のカテゴリ単位で与える。
2. タイトル中のマッチは概要中のマッチより強く数える
   タイトルに出てくる語がその記事の主題であることが多いため。
3. 新しさ
   同程度の確からしさなら新しい記事を優先する。
4. キーワードフィルタ免除フィードへの下駄
   免除フィード（arXiv等）はマッチ0件でも通過するため、そのままだとスコア0で
   常に最下位に沈み、クォータで枠を確保しても中身が新しさ順にしかならない。
5. ウォッチリストの企業の決算の記事への加点
   会社名（watchlist.yaml）と決算の語（keywords.yaml の watchlist.earnings_words）が
   両方出る記事。決算の朝に、その記事が BTC・FRB の記事に埋もれないようにする。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from good_morning.models import Article
from good_morning.selector.filters import compile_keyword_pattern, matched_keywords_in_text
from good_morning.selector.keywords import (
    DEFAULT_KEYWORD_WEIGHT,
    KEYWORD_GROUPS,
    KEYWORD_WEIGHTS,
    WATCHLIST_KEYWORDS,
    WATCHLIST_SETTINGS,
)

JST = ZoneInfo("Asia/Tokyo")

# config/keywords.yaml のカテゴリ名 → 重み（YAML の weight。大原則4: 設定は YAML に寄せる）
KEYWORD_CATEGORY_WEIGHTS = KEYWORD_WEIGHTS

# タイトル中のマッチを概要中のマッチの何倍に数えるか
TITLE_MULTIPLIER = 2.0

# 新しさによる加点の上限と半減期。公開直後が最大で、半減期ごとに半分になる。
RECENCY_MAX_POINTS = 3.0
RECENCY_HALF_LIFE_HOURS = 24.0

# キーワードフィルタ免除フィードに与える下駄
EXEMPT_SOURCE_BASE_POINTS = 2.0

# ウォッチリストの企業の決算の記事（会社名と決算の語が両方出る記事）への加点
EARNINGS_BONUS_POINTS = WATCHLIST_SETTINGS.earnings_bonus
_WATCHLIST_WORDS = frozenset(WATCHLIST_KEYWORDS)
_EARNINGS_PATTERNS = [compile_keyword_pattern(w) for w in WATCHLIST_SETTINGS.earnings_words]


def keyword_weight(keyword: str) -> float:
    """キーワード1件あたりの重みを返す"""
    for category, keywords in KEYWORD_GROUPS.items():
        if keyword in keywords:
            return KEYWORD_CATEGORY_WEIGHTS.get(category, DEFAULT_KEYWORD_WEIGHT)
    return DEFAULT_KEYWORD_WEIGHT


def keyword_score(article: Article, ignore: frozenset[str] = frozenset()) -> float:
    """マッチしたキーワードの重み和（タイトル中のマッチは重く数える。ignore の語は数えない）"""
    title_hits = set(matched_keywords_in_text(article.title)) - ignore
    summary_hits = set(matched_keywords_in_text(article.summary or "")) - title_hits - ignore

    return sum(keyword_weight(kw) * TITLE_MULTIPLIER for kw in title_hits) + sum(
        keyword_weight(kw) for kw in summary_hits
    )


def is_earnings_article(article: Article, ignore: frozenset[str] = frozenset()) -> bool:
    """ウォッチリストの会社名と決算の語が、タイトルか概要に両方出る記事か"""
    if not _WATCHLIST_WORDS or not _EARNINGS_PATTERNS:
        return False
    text = article.title + " " + (article.summary or "")
    names = (set(matched_keywords_in_text(text)) & _WATCHLIST_WORDS) - ignore
    return bool(names) and any(pattern.search(text) for pattern in _EARNINGS_PATTERNS)


def earnings_bonus(article: Article, ignore: frozenset[str] = frozenset()) -> float:
    """ウォッチリストの企業の決算の記事への加点"""
    return EARNINGS_BONUS_POINTS if is_earnings_article(article, ignore) else 0.0


def recency_score(article: Article, now: datetime | None = None) -> float:
    """公開からの経過時間で半減する加点

    published が無い記事は日付フィルタで既に落ちているが、念のため0点として扱う。
    """
    if article.published is None:
        return 0.0

    now = now or datetime.now(JST)
    age_hours = (now - article.published).total_seconds() / 3600
    if age_hours < 0:  # 未来日付の記事は最新扱い
        age_hours = 0.0

    return RECENCY_MAX_POINTS * (0.5 ** (age_hours / RECENCY_HALF_LIFE_HOURS))


def score_article(
    article: Article,
    exempt_sources: frozenset[str] = frozenset(),
    now: datetime | None = None,
    ignore_by_source: dict[str, frozenset[str]] | None = None,
) -> float:
    """記事の総合スコアを算出する"""
    ignore = (ignore_by_source or {}).get(article.source, frozenset())
    score = keyword_score(article, ignore) + earnings_bonus(article, ignore) + recency_score(article, now=now)
    if article.source in exempt_sources:
        score += EXEMPT_SOURCE_BASE_POINTS
    return score


def score_articles(
    articles: list[Article],
    exempt_sources: frozenset[str] = frozenset(),
    now: datetime | None = None,
    ignore_by_source: dict[str, frozenset[str]] | None = None,
) -> list[Article]:
    """記事リストに score を付与する（同じオブジェクトを書き換えて返す）"""
    now = now or datetime.now(JST)
    for article in articles:
        article.score = score_article(
            article, exempt_sources=exempt_sources, now=now, ignore_by_source=ignore_by_source
        )
    return articles
