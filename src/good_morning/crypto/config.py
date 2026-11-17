"""config/scoring.yaml の読み込み"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from good_morning.paths import CONFIG_DIR

AVAILABLE_SMA_PERIODS = (5, 20, 25, 50, 75, 200)


class JudgementConfig(BaseModel):
    bullish_at: int = 2
    bearish_at: int = -2

    @model_validator(mode="after")
    def _check(self):
        if self.bearish_at >= self.bullish_at:
            raise ValueError("judgement: bearish_at は bullish_at より小さくしてください")
        return self


class RsiScores(BaseModel):
    oversold: int = -1
    weak: int = -1
    neutral: int = 0
    strong: int = 1
    overbought: int = 1


class RsiConfig(BaseModel):
    period: int = 14
    oversold: float = 30
    weak: float = 45
    strong: float = 55
    overbought: float = 70
    scores: RsiScores = Field(default_factory=RsiScores)
    history_bars: int = 7

    @model_validator(mode="after")
    def _check(self):
        if not (self.oversold < self.weak <= self.strong < self.overbought):
            raise ValueError("rsi: oversold < weak <= strong < overbought の順にしてください")
        return self


class IchimokuConfig(BaseModel):
    shift: int = 26


class MovingAverageConfig(BaseModel):
    periods: list[int] = Field(default_factory=lambda: [25, 75, 200])
    allow_partial: bool = True

    @model_validator(mode="after")
    def _check(self):
        unknown = [p for p in self.periods if p not in AVAILABLE_SMA_PERIODS]
        if unknown:
            raise ValueError(
                f"moving_average: 使えない本数があります {unknown}（使えるのは {AVAILABLE_SMA_PERIODS}）"
            )
        if len(self.periods) < 2:
            raise ValueError("moving_average: periods は2本以上にしてください")
        return self


class ScoringConfig(BaseModel):
    judgement: JudgementConfig = Field(default_factory=JudgementConfig)
    rsi: RsiConfig = Field(default_factory=RsiConfig)
    ichimoku: IchimokuConfig = Field(default_factory=IchimokuConfig)
    moving_average: MovingAverageConfig = Field(default_factory=MovingAverageConfig)


def load_scoring_config(config_path: Path | None = None) -> ScoringConfig:
    config_path = config_path or CONFIG_DIR / "scoring.yaml"
    with open(config_path, encoding="utf-8") as f:
        return ScoringConfig(**(yaml.safe_load(f) or {}))
