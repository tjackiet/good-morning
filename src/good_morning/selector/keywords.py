"""キーワード定義（記事選定のキーワードフィルタとスコアリング用）

キーワード本体とカテゴリごとの重みは config/keywords.yaml で管理する:

    keywords:
      暗号資産:
        weight: 3
        words: [ビットコイン, Bitcoin, ...]

（aion の形式 `カテゴリ: [語, ...]` も読める。その場合の重みは DEFAULT_KEYWORD_WEIGHT）

ウォッチリストの会社名（watchlist.yaml の stocks[].keywords）も「ウォッチリストの企業」
カテゴリとして足す（重みは keywords.yaml の watchlist.weight）。会社名と決算の語が両方出る
記事への加点は scoring が行う。
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from good_morning.paths import CONFIG_DIR

logger = logging.getLogger(__name__)

DEFAULT_KEYWORD_WEIGHT = 1.0
WATCHLIST_CATEGORY = "ウォッチリストの企業"
DEFAULT_WATCHLIST_WEIGHT = 3.0


@dataclass(frozen=True)
class WatchlistKeywordSettings:
    weight: float = DEFAULT_WATCHLIST_WEIGHT  # 会社名がマッチしたときの重み
    earnings_words: tuple[str, ...] = ()  # 会社名と一緒に出たら決算の記事とみなす語
    earnings_bonus: float = 0.0  # 決算の記事への加点
    earnings_slots: int = 0  # 主要ニュースのうち、決算の記事に優先して回す本数


def _load_yaml(config_path: Path | None) -> dict:
    if config_path is None:
        config_path = CONFIG_DIR / "keywords.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_watchlist_settings(config_path: Path | None = None) -> WatchlistKeywordSettings:
    data = _load_yaml(config_path).get("watchlist") or {}
    return WatchlistKeywordSettings(
        weight=float(data.get("weight", DEFAULT_WATCHLIST_WEIGHT)),
        earnings_words=tuple(str(w) for w in data.get("earnings_words", [])),
        earnings_bonus=float(data.get("earnings_bonus", 0.0)),
        earnings_slots=max(0, int(data.get("earnings_slots", 0))),
    )


def load_watchlist_keywords(config_dir: Path | None = None) -> list[str]:
    """ウォッチリストの会社名（重複なし）。読めなければ空にして続ける（ニュースは止めない）"""
    from good_morning.watchlist import load_watchlist

    try:
        watchlist = load_watchlist(config_dir, quiet=True)
    except Exception as e:  # noqa: BLE001 - 会社名がなくても記事は選べる
        logger.warning("ニュースのキーワード: ウォッチリストを読めないため会社名を使いません（%s）", type(e).__name__)
        return []
    words: list[str] = []
    for stock in watchlist.stocks:
        words.extend(w for w in stock.keywords if w not in words)
    return words


def load_keyword_config(config_path: Path | None = None) -> dict[str, tuple[float, list[str]]]:
    """{カテゴリ: (重み, [語, ...])} を返す（keywords.yaml の keywords だけ。会社名は含まない）"""
    data = _load_yaml(config_path)

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
WATCHLIST_SETTINGS = load_watchlist_settings()
WATCHLIST_KEYWORDS = load_watchlist_keywords()
if WATCHLIST_KEYWORDS:
    # 先頭に置く: 「企業」カテゴリと重なる語（Coinbase など）はウォッチリストの重みで数える
    _CONFIG = {WATCHLIST_CATEGORY: (WATCHLIST_SETTINGS.weight, WATCHLIST_KEYWORDS), **_CONFIG}
KEYWORD_GROUPS = {category: words for category, (_, words) in _CONFIG.items()}
KEYWORD_WEIGHTS = {category: weight for category, (weight, _) in _CONFIG.items()}
KEYWORDS = list(dict.fromkeys(kw for group in KEYWORD_GROUPS.values() for kw in group))
