"""config/etf.yaml の読み込み"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from good_morning.paths import CONFIG_DIR


class Fund(BaseModel):
    ticker: str = Field(pattern=r"^[A-Z0-9]{1,10}$")  # URL のパスに入るので英大文字と数字だけ
    issuer: str  # 表に出す運用会社の名前


class EtfConfig(BaseModel):
    symbol: str = "BTC"
    country_code: str = "US"
    recent_days: int = Field(default=5, ge=1, le=20)  # 合計の推移を出す営業日数
    funds: list[Fund] = Field(default_factory=list)  # 銘柄別に出す ETF（この順）


def load_etf_config(config_path: Path | None = None) -> EtfConfig:
    config_path = config_path or CONFIG_DIR / "etf.yaml"
    with open(config_path, encoding="utf-8") as f:
        return EtfConfig(**(yaml.safe_load(f) or {}))
