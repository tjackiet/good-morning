"""スコア順の並べ替えとカテゴリ別クォータによる要約対象の選定

（aion より）これ以前は summarizer が articles[:max_articles] で先頭N件を切っていた。
記事はフィード取得順（feeds.yaml の並び順）で積まれているため、先頭のフィードが
要約枠を全部食い、後ろのフィードは一件も選ばれないという構造になっていた。
選定はここに集約し、summarizer は渡された記事を要約するだけにする。

カテゴリごとの配分は config/feeds.yaml の categories.<カテゴリ>.quota で決める。
"""

from collections.abc import Callable

from good_morning.collector.rss import load_feeds_config
from good_morning.models import Article


def load_category_quota() -> dict[str, int]:
    """feeds.yaml のカテゴリごとの配分比（max_articles が合計と違えば比率として按分する）"""
    return {name: c.quota for name, c in load_feeds_config().categories.items()}


CATEGORY_QUOTA = load_category_quota()
# 既定の要約本数はクォータの合計（指示書: 主要ニュースは3〜5本）
DEFAULT_MAX_ARTICLES = sum(CATEGORY_QUOTA.values())


def _sort_key(article: Article) -> tuple:
    """スコア降順・新しい順で並べる。同点時の順序を安定させるため title まで見る。

    published が None の記事は最後に回す。
    """
    published_rank = -article.published.timestamp() if article.published else float("inf")
    return (-article.score, published_rank, article.title)


def rank_articles(articles: list[Article]) -> list[Article]:
    """スコア降順に並べ替えた新しいリストを返す"""
    return sorted(articles, key=_sort_key)


def allocate_quota(max_articles: int, quota: dict[str, int] | None = None) -> dict[str, int]:
    """配分比を max_articles 件に按分する（最大剰余法）

    合計が max_articles ちょうどになるよう、切り捨てで余った枠を小数部の大きい
    カテゴリから順に配る。
    """
    quota = quota or CATEGORY_QUOTA
    total_weight = sum(quota.values())
    if total_weight <= 0 or max_articles <= 0:
        return dict.fromkeys(quota, 0)

    exact = {cat: max_articles * weight / total_weight for cat, weight in quota.items()}
    allocated = {cat: int(value) for cat, value in exact.items()}

    remaining = max_articles - sum(allocated.values())
    # 小数部が大きい順（同率はカテゴリ名順）に余りを配る
    for category in sorted(exact, key=lambda c: (-(exact[c] - allocated[c]), c))[:remaining]:
        allocated[category] += 1

    return allocated


def select_for_summary(
    articles: list[Article],
    max_articles: int = DEFAULT_MAX_ARTICLES,
    quota: dict[str, int] | None = None,
    priority: Callable[[Article], bool] | None = None,
    priority_slots: int = 0,
) -> list[Article]:
    """要約対象をスコア順・カテゴリ別クォータで選ぶ

    priority に当たる記事（ウォッチリストの企業の決算の記事など）があれば、スコア上位から
    priority_slots 本までを先に取る（その記事のカテゴリの枠も使う。合計本数は変えない）。
    次に各カテゴリに割り当てた枠までスコア上位から取り、記事数が枠に満たない
    カテゴリの余り枠は全体のスコア順で埋める（クォータのせいで要約枠が
    空くのを避けるため）。返り値は全体のスコア順。
    """
    ranked = rank_articles(articles)
    allocated = allocate_quota(max_articles, quota)

    selected: list[Article] = []
    chosen: set[int] = set()
    used_slots: dict[str, int] = dict.fromkeys(allocated, 0)

    def take(article: Article) -> None:
        selected.append(article)
        chosen.add(id(article))
        used_slots[article.category] = used_slots.get(article.category, 0) + 1

    if priority is not None and priority_slots > 0:
        for article in ranked:
            if len(selected) >= min(priority_slots, max_articles):
                break
            if priority(article):
                take(article)

    for article in ranked:
        if len(selected) >= max_articles:
            break
        if id(article) in chosen:
            continue
        if used_slots.get(article.category, 0) < allocated.get(article.category, 0):
            take(article)

    # クォータで埋まらなかった枠をスコア順で補充
    for article in ranked:
        if len(selected) >= max_articles:
            break
        if id(article) not in chosen:
            take(article)

    return rank_articles(selected)


def category_breakdown(articles: list[Article]) -> dict[str, int]:
    """カテゴリごとの件数を数える（ログ表示用）"""
    counts: dict[str, int] = {}
    for article in articles:
        counts[article.category] = counts.get(article.category, 0) + 1
    return counts
