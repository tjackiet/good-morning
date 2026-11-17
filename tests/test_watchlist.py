"""good_morning.watchlist のテスト"""

import logging
import shutil

import pytest

from good_morning.paths import CONFIG_DIR
from good_morning.watchlist import (
    MAX_CRYPTO_WATCH,
    MAX_STOCKS,
    WATCHLIST_EXAMPLE_FILE,
    WATCHLIST_FILE,
    load_watchlist,
)


@pytest.fixture
def config_dir(tmp_path):
    return tmp_path


def _write(config_dir, name: str, text: str):
    (config_dir / name).write_text(text, encoding="utf-8")


def test_falls_back_to_example_with_warning(config_dir, caplog):
    """watchlist.yaml がなければ example を読み、警告を出す"""
    _write(config_dir, WATCHLIST_EXAMPLE_FILE, "crypto:\n  main: btc_jpy\n  watch: [eth_jpy]\n")

    with caplog.at_level(logging.WARNING):
        watchlist = load_watchlist(config_dir)

    assert watchlist.is_example
    assert watchlist.crypto.watch == ["eth_jpy"]
    assert any(WATCHLIST_FILE in r.getMessage() for r in caplog.records)


def test_prefers_watchlist_yaml_over_example(config_dir, caplog):
    _write(config_dir, WATCHLIST_EXAMPLE_FILE, "crypto:\n  watch: [eth_jpy]\n")
    _write(config_dir, WATCHLIST_FILE, "crypto:\n  watch: [xrp_jpy]\n")

    with caplog.at_level(logging.WARNING):
        watchlist = load_watchlist(config_dir)

    assert not watchlist.is_example
    assert watchlist.crypto.watch == ["xrp_jpy"]
    assert caplog.records == []


def test_truncates_over_limit_from_head(config_dir, caplog):
    """上限を超えたら先頭から順に採用し、残りは警告して捨てる"""
    pairs = [f"c{i}_jpy" for i in range(MAX_CRYPTO_WATCH + 2)]
    stocks = "".join(f"  - ticker: T{i}\n    name: 銘柄{i}\n" for i in range(MAX_STOCKS + 1))
    _write(config_dir, WATCHLIST_FILE, f"crypto:\n  watch: [{', '.join(pairs)}]\nstocks:\n{stocks}")

    with caplog.at_level(logging.WARNING):
        watchlist = load_watchlist(config_dir)

    assert watchlist.crypto.watch == pairs[:MAX_CRYPTO_WATCH]
    assert [s.ticker for s in watchlist.stocks] == [f"T{i}" for i in range(MAX_STOCKS)]
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "c5_jpy" in messages and "c6_jpy" in messages
    assert "T10" in messages


def test_normalizes_case(config_dir):
    _write(
        config_dir,
        WATCHLIST_FILE,
        "crypto:\n  main: BTC_JPY\n  watch: [' Eth_Jpy ']\n"
        "stocks:\n  - ticker: nvda\n    name: エヌビディア\n    related: [tsm]\n",
    )

    watchlist = load_watchlist(config_dir)

    assert watchlist.crypto.main == "btc_jpy"
    assert watchlist.crypto.watch == ["eth_jpy"]
    assert watchlist.stocks[0].ticker == "NVDA"
    assert watchlist.stocks[0].related == ["TSM"]


def test_shipped_example_is_valid_and_within_limits(tmp_path):
    """リポジトリに入っている watchlist.example.yaml がそのまま読めること"""
    shutil.copy(CONFIG_DIR / WATCHLIST_EXAMPLE_FILE, tmp_path / WATCHLIST_EXAMPLE_FILE)

    watchlist = load_watchlist(tmp_path)

    assert watchlist.is_example
    assert watchlist.crypto.main == "btc_jpy"
    assert len(watchlist.crypto.watch) == MAX_CRYPTO_WATCH
    assert [s.ticker for s in watchlist.stocks] == ["NVDA", "COIN", "MSTR"]
