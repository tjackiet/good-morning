"""pytest共通フィクスチャ"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from good_morning.models import Article

FIXTURES_DIR = Path(__file__).parent / "fixtures"
JST = ZoneInfo("Asia/Tokyo")

# NY の取引開始前（2026-11-17 22:50 JST = 08:50 ET）に取得した実データ。
# ^TNX と ^VIX には、この時点で当日（11/17）の形成中の足が入っている。
YF_PRE_OPEN_FIXTURE = "yfinance/history_20261117_2250.json"
YF_PRE_OPEN_CAPTURED_AT = datetime(2026, 11, 17, 22, 50, tzinfo=JST)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


# 2026-11-17 23:09 JST に bitbank-lab-mcp から取得した実データ（使う部分だけに切り詰めたもの）
BITBANK_FIXTURE = "bitbank/snapshot_20261117_2309.json"


@pytest.fixture(autouse=True)
def _block_network(monkeypatch):
    """テストから yfinance・bitbank-lab-mcp（ネットワーク）に触れたら失敗させる（大原則5）"""

    def _blocked_yf(*args, **kwargs):
        raise RuntimeError("テストから yfinance にアクセスしようとしました。fixtures を使ってください")

    def _blocked_mcp(*args, **kwargs):
        raise RuntimeError("テストから bitbank-lab-mcp に接続しようとしました。fixtures を使ってください")

    monkeypatch.setattr("good_morning.collector.market_data.yf.Ticker", _blocked_yf)
    monkeypatch.setattr("good_morning.collector.bitbank_mcp.fetch_snapshot", _blocked_mcp)


def load_fixture_json(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def fake_bitbank(monkeypatch):
    """bitbank-lab-mcp の取得を fixtures から返す偽物に差し替える

    使い方: calls = fake_bitbank(BITBANK_FIXTURE) / fake_bitbank(data_dict)
    返り値のリストに、fetch_snapshot が呼ばれた回数分の呼び出し内容が入る。
    """
    from good_morning.collector.bitbank_mcp import BitbankSnapshot

    def _install(source: str | dict) -> list:
        data = load_fixture_json(source) if isinstance(source, str) else source
        calls: list = []

        def _fake_fetch(tool_calls=None):
            calls.append(tool_calls)
            return BitbankSnapshot(
                results=dict(data.get("results", {})), errors=dict(data.get("errors", {}))
            )

        monkeypatch.setattr("good_morning.collector.bitbank_mcp.fetch_snapshot", _fake_fetch)
        return calls

    return _install


def history_frame(series: dict) -> pd.DataFrame:
    """fixtures の1銘柄分を yfinance の history() と同じ形の DataFrame に戻す"""
    timestamps = [ts for ts, _ in series["rows"]]
    index = pd.to_datetime(timestamps, utc=True).tz_convert(series["timezone"])
    closes = [np.nan if close is None else close for _, close in series["rows"]]
    return pd.DataFrame({"Close": closes}, index=index)


@pytest.fixture
def fake_yfinance(monkeypatch):
    """yfinance.Ticker を fixtures から返す偽物に差し替える

    使い方: fake_yfinance(YF_PRE_OPEN_FIXTURE) / fake_yfinance(data_dict)
    fixtures にない銘柄は空の DataFrame を返す（銘柄コードの誤りと同じ振る舞い）。
    """

    def _install(source: str | dict) -> dict:
        if isinstance(source, str):
            data = json.loads((FIXTURES_DIR / source).read_text(encoding="utf-8"))
        else:
            data = source

        class FakeTicker:
            def __init__(self, ticker: str):
                self.ticker = ticker

            def history(self, period=None, interval=None, auto_adjust=None, actions=None):
                # 騰落率は日足の終値から計算する（大原則2）
                assert interval == "1d"
                series = data["series"].get(self.ticker)
                return pd.DataFrame() if series is None else history_frame(series)

        monkeypatch.setattr("good_morning.collector.market_data.yf.Ticker", FakeTicker)
        return data

    return _install


@pytest.fixture
def make_article():
    """テスト用のArticleを組み立てるファクトリフィクスチャ

    published_offset は datetime.now(JST) からの相対時間。None なら published=None。
    """

    def _make(
        title: str = "テスト記事",
        summary: str | None = None,
        source: str = "テストソース",
        category: str = "tech",
        published_offset: timedelta | None = None,
    ) -> Article:
        published = None
        if published_offset is not None:
            published = datetime.now(JST) + published_offset

        return Article(
            title=title,
            url="https://example.com/article",
            source=source,
            category=category,
            published=published,
            summary=summary,
        )

    return _make
