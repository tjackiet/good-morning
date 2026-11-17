"""config/markets.yaml の読み込み"""

from datetime import time, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field, model_validator

from good_morning.paths import CONFIG_DIR

Basis = Literal["close", "live"]
ValueFormat = Literal["price", "yield"]


class MarketItem(BaseModel):
    ticker: str
    name: str
    basis: Basis = "close"
    format: ValueFormat = "price"
    decimals: int = 2
    group: str | None = None


class SectorItem(BaseModel):
    ticker: str
    name: str


class MarketClose(BaseModel):
    """NY終値の確定時刻"""

    timezone: str = "America/New_York"
    time: str = "16:00"
    settle_minutes: int = 30

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def close_time(self) -> time:
        hour, minute = (int(part) for part in self.time.split(":"))
        return time(hour, minute)

    @property
    def settled_time(self) -> time:
        """終値が確定したとみなす時刻（close_time + settle_minutes）"""
        base = timedelta(hours=self.close_time.hour, minutes=self.close_time.minute)
        total = base + timedelta(minutes=self.settle_minutes)
        return time(int(total.total_seconds() // 3600), int(total.total_seconds() % 3600 // 60))


class MarketsConfig(BaseModel):
    us_market_close: MarketClose = Field(default_factory=MarketClose)
    optional_groups: dict[str, bool] = Field(default_factory=dict)
    markets: list[MarketItem]
    sectors: list[SectorItem]

    @model_validator(mode="after")
    def _check_groups(self):
        unknown = {m.group for m in self.markets if m.group} - set(self.optional_groups)
        if unknown:
            raise ValueError(
                f"optional_groups に定義されていないグループがあります: {', '.join(sorted(unknown))}"
            )
        return self

    def enabled_markets(self) -> list[MarketItem]:
        """任意項目のうちオフのグループを除いた、表示する項目（設定の順）"""
        return [m for m in self.markets if m.group is None or self.optional_groups[m.group]]


def load_markets_config(config_path: Path | None = None) -> MarketsConfig:
    config_path = config_path or CONFIG_DIR / "markets.yaml"
    with open(config_path, encoding="utf-8") as f:
        return MarketsConfig(**yaml.safe_load(f))
