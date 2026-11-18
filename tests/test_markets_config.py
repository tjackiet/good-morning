"""config/markets.yaml のテスト"""

from datetime import time

import pytest
from pydantic import ValidationError

from good_morning.markets.config import MarketClose, MarketsConfig, load_markets_config


def test_shipped_config_matches_spec():
    """指示書「5. レポートの骨子」のマーケット一覧とセクター（任意項目は初期値オン）"""
    config = load_markets_config()

    assert [m.ticker for m in config.enabled_markets()] == [
        "^TNX", "JPY=X", "^DJI", "^GSPC", "^IXIC", "CL=F", "GC=F",
        "^VIX", "DX-Y.NYB", "ES=F", "NQ=F", "YM=F",
    ]  # fmt: skip
    assert all(config.optional_groups.values())
    assert [s.ticker for s in config.sectors] == [
        "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC",
    ]  # fmt: skip
    tnx = config.markets[0]
    assert (tnx.format, tnx.basis) == ("yield", "close")
    assert config.tiles == ["^DJI", "^GSPC", "^IXIC", "JPY=X", "^TNX", "CL=F"]


def test_unknown_tile_ticker_is_rejected():
    with pytest.raises(ValidationError, match="tiles"):
        MarketsConfig(markets=[{"ticker": "^DJI", "name": "NYダウ"}], sectors=[], tiles=["^DJI", "^N225"])


def test_unknown_group_is_rejected():
    with pytest.raises(ValidationError, match="optional_groups"):
        MarketsConfig(
            optional_groups={},
            markets=[{"ticker": "^VIX", "name": "VIX", "group": "vix"}],
            sectors=[],
        )


def test_settled_time():
    assert MarketClose(time="16:00", settle_minutes=30).settled_time == time(16, 30)
    assert MarketClose(time="15:45", settle_minutes=30).settled_time == time(16, 15)
