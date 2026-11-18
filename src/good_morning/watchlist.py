"""ウォッチリスト設定（config/watchlist.yaml）の読み込み

watchlist.yaml は個人の設定なので .gitignore で除外しており、リポジトリには
watchlist.example.yaml だけが入っている。watchlist.yaml がなければ example を
読み込み、警告を出す（レポート生成は止めない）。

上限（暗号資産5銘柄・米国株10銘柄）を超えた分は、先頭から順に採用して残りを捨てる。
bitbank の取扱銘柄との照合はフェーズ2で行う。
"""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from good_morning.paths import CONFIG_DIR

logger = logging.getLogger(__name__)

WATCHLIST_FILE = "watchlist.yaml"
WATCHLIST_EXAMPLE_FILE = "watchlist.example.yaml"
MAX_CRYPTO_WATCH = 5
MAX_STOCKS = 10


class CryptoWatchlist(BaseModel):
    main: str = "btc_jpy"
    watch: list[str] = Field(default_factory=list)

    @field_validator("main")
    @classmethod
    def _normalize_main(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("watch")
    @classmethod
    def _normalize_watch(cls, value: list[str]) -> list[str]:
        return [pair.strip().lower() for pair in value]


class StockEntry(BaseModel):
    ticker: str
    name: str
    related: list[str] = Field(default_factory=list)
    # ニュースで拾う会社名（日本語・英語）。主要ニュースの記事選定のキーワードに足す
    keywords: list[str] = Field(default_factory=list)

    @field_validator("keywords")
    @classmethod
    def _strip_keywords(cls, value: list[str]) -> list[str]:
        return [word.strip() for word in value if word.strip()]

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("related")
    @classmethod
    def _normalize_related(cls, value: list[str]) -> list[str]:
        return [ticker.strip().upper() for ticker in value]


class Watchlist(BaseModel):
    crypto: CryptoWatchlist = Field(default_factory=CryptoWatchlist)
    stocks: list[StockEntry] = Field(default_factory=list)
    # どのファイルから読み込んだか（example にフォールバックしたかをヘッダー等で示せるように）
    source: Path | None = None

    @property
    def is_example(self) -> bool:
        return self.source is not None and self.source.name == WATCHLIST_EXAMPLE_FILE


def resolve_watchlist_path(config_dir: Path | None = None, quiet: bool = False) -> Path:
    """読み込むファイルを決める。watchlist.yaml がなければ example を返して警告する

    quiet=True は警告を出さない（ニュースのキーワードなど、2度目の読み込みで警告が重ならないように）。
    """
    config_dir = config_dir or CONFIG_DIR
    path = config_dir / WATCHLIST_FILE
    if path.exists():
        return path

    example = config_dir / WATCHLIST_EXAMPLE_FILE
    if quiet:
        return example
    logger.warning(
        "%s が見つからないため %s を読み込みます。"
        "手元で `cp config/%s config/%s` してから銘柄を編集してください。",
        WATCHLIST_FILE,
        WATCHLIST_EXAMPLE_FILE,
        WATCHLIST_EXAMPLE_FILE,
        WATCHLIST_FILE,
    )
    return example


def _truncate(items: list, limit: int, label: str) -> list:
    if len(items) <= limit:
        return items
    dropped = items[limit:]
    logger.warning(
        "%sが上限 %d 件を超えています（%d 件）。先頭 %d 件を採用し、残りを無視します: %s",
        label,
        limit,
        len(items),
        limit,
        ", ".join(str(getattr(item, "ticker", item)) for item in dropped),
    )
    return items[:limit]


def load_watchlist(config_dir: Path | None = None, quiet: bool = False) -> Watchlist:
    """ウォッチリストを読み込み、上限を超えた分を切り詰めて返す"""
    path = resolve_watchlist_path(config_dir, quiet=quiet)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    watchlist = Watchlist(**data, source=path)
    watchlist.crypto.watch = _truncate(
        watchlist.crypto.watch, MAX_CRYPTO_WATCH, "暗号資産ウォッチリスト"
    )
    watchlist.stocks = _truncate(watchlist.stocks, MAX_STOCKS, "株式ウォッチリスト")
    return watchlist
