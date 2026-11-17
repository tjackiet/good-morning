"""config/events.yaml の読み込み"""

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from good_morning.paths import CONFIG_DIR

Importance = Literal["高", "中", "低"]


class Horizon(BaseModel):
    detail_days: int = 7
    total_days: int = 30

    @model_validator(mode="after")
    def _check(self):
        if not (0 <= self.detail_days <= self.total_days):
            raise ValueError("horizon: 0 <= detail_days <= total_days にしてください")
        return self


class CategoryDefaults(BaseModel):
    timezone: str = "Asia/Tokyo"
    time: str | None = None
    importance: Importance = "中"
    note: str | None = None


class StaticEvent(BaseModel):
    category: str
    date: date
    title: str
    time: str | None = None
    timezone: str | None = None
    importance: Importance | None = None
    note: str | None = None
    estimated: bool = False


class FredRelease(BaseModel):
    name: str  # FRED の release_name（完全一致）
    title: str
    importance: Importance = "中"
    time: str | None = None


class FredConfig(BaseModel):
    timezone: str = "America/New_York"
    releases: list[FredRelease] = Field(default_factory=list)


class EarningsImportance(BaseModel):
    watchlist: Importance = "中"
    related: Importance = "低"


class EarningsConfig(BaseModel):
    importance: EarningsImportance = Field(default_factory=EarningsImportance)


class EventsConfig(BaseModel):
    horizon: Horizon = Field(default_factory=Horizon)
    categories: dict[str, CategoryDefaults] = Field(default_factory=dict)
    events: list[StaticEvent] = Field(default_factory=list)
    fred: FredConfig = Field(default_factory=FredConfig)
    earnings: EarningsConfig = Field(default_factory=EarningsConfig)

    @model_validator(mode="after")
    def _check_categories(self):
        unknown = {e.category for e in self.events} - set(self.categories)
        if unknown:
            raise ValueError(f"categories に定義されていない区分があります: {', '.join(sorted(unknown))}")
        return self


def load_events_config(config_path: Path | None = None) -> EventsConfig:
    config_path = config_path or CONFIG_DIR / "events.yaml"
    with open(config_path, encoding="utf-8") as f:
        return EventsConfig(**(yaml.safe_load(f) or {}))
