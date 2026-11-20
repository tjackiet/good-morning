"""config/demand.yaml の読み込み"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from good_morning.paths import CONFIG_DIR


class StablecoinConfig(BaseModel):
    change_days: int = Field(default=7, ge=1, le=30)  # 合計の増減を出す日数（前日比とあわせて出す）
    breakdown: list[str] = Field(default_factory=lambda: ["USDT", "USDC"])  # 内訳を出す銘柄


class PremiumConfig(BaseModel):
    coinbase_product: str = Field(default="BTC-USD", pattern=r"^[A-Z0-9]{2,10}-[A-Z]{3,4}$")
    reference_symbol: str = Field(default="BTCUSDT", pattern=r"^[A-Z0-9]{5,15}$")  # Binance の現物


class DemandConfig(BaseModel):
    stablecoins: StablecoinConfig = Field(default_factory=StablecoinConfig)
    premium: PremiumConfig = Field(default_factory=PremiumConfig)


def load_demand_config(config_path: Path | None = None) -> DemandConfig:
    config_path = config_path or CONFIG_DIR / "demand.yaml"
    with open(config_path, encoding="utf-8") as f:
        return DemandConfig(**(yaml.safe_load(f) or {}))
