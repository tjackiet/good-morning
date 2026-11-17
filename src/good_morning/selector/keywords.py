"""キーワード定義（記事選定のキーワードフィルタとスコアリング用）

キーワード本体とカテゴリごとの重みは config/keywords.yaml で管理する:

    keywords:
      暗号資産:
        weight: 3
        words: [ビットコイン, Bitcoin, ...]

（aion の形式 `カテゴリ: [語, ...]` も読める。その場合の重みは DEFAULT_KEYWORD_WEIGHT）
"""

from pathlib import Path

import yaml

from good_morning.paths import CONFIG_DIR

DEFAULT_KEYWORD_WEIGHT = 1.0


def load_keyword_config(config_path: Path | None = None) -> dict[str, tuple[float, list[str]]]:
    """{カテゴリ: (重み, [語, ...])} を返す"""
    if config_path is None:
        config_path = CONFIG_DIR / "keywords.yaml"

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    groups: dict[str, tuple[float, list[str]]] = {}
    for category, value in data["keywords"].items():
        if isinstance(value, dict):
            weight = float(value.get("weight", DEFAULT_KEYWORD_WEIGHT))
            words = [str(w) for w in value.get("words", [])]
        else:
            weight, words = DEFAULT_KEYWORD_WEIGHT, [str(w) for w in value]
        groups[category] = (weight, words)
    return groups


def load_keyword_groups(config_path: Path | None = None) -> dict[str, list[str]]:
    """キーワードをYAMLのカテゴリ構造を保ったまま読み込む

    マッチング（filters）はカテゴリを区別しないが、スコアリング（scoring）は
    カテゴリごとの重みを引くためにこの構造を使う。
    """
    return {category: words for category, (_, words) in load_keyword_config(config_path).items()}


def load_keywords(config_path: Path | None = None) -> list[str]:
    """キーワードをYAMLから読み込み、カテゴリを平坦化したリストで返す"""
    return [kw for words in load_keyword_groups(config_path).values() for kw in words]


_CONFIG = load_keyword_config()
KEYWORD_GROUPS = {category: words for category, (_, words) in _CONFIG.items()}
KEYWORD_WEIGHTS = {category: weight for category, (weight, _) in _CONFIG.items()}
KEYWORDS = [kw for group in KEYWORD_GROUPS.values() for kw in group]
