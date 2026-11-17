"""キーワード定義（記事選定のキーワードフィルタ用）

キーワード本体は config/keywords.yaml で管理する。
"""

from pathlib import Path

import yaml

from good_morning.paths import CONFIG_DIR


def load_keyword_groups(config_path: Path | None = None) -> dict[str, list[str]]:
    """キーワードをYAMLのカテゴリ構造を保ったまま読み込む

    マッチング（filters）はカテゴリを区別しないが、スコアリング（scoring）は
    カテゴリごとの重みを引くためにこの構造を使う。
    """
    if config_path is None:
        config_path = CONFIG_DIR / "keywords.yaml"

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return {category: list(keywords) for category, keywords in data["keywords"].items()}


def load_keywords(config_path: Path | None = None) -> list[str]:
    """キーワードをYAMLから読み込み、カテゴリを平坦化したリストで返す"""
    keywords: list[str] = []
    for category_keywords in load_keyword_groups(config_path).values():
        keywords.extend(category_keywords)
    return keywords


KEYWORD_GROUPS = load_keyword_groups()
KEYWORDS = [kw for group in KEYWORD_GROUPS.values() for kw in group]
