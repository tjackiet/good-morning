"""good_morning.crypto.technicals のテスト（数値の読み取りと判定ルール）"""

from dataclasses import replace
from datetime import date

import pytest
from conftest import BITBANK_FIXTURE, load_fixture_json

from good_morning.crypto.config import ScoringConfig, load_scoring_config
from good_morning.crypto.technicals import (
    TechnicalsError,
    assess,
    cloud_signal,
    ma_order_signal,
    parse_technicals,
    rsi_zone,
    sanyaku_signal,
)

CONFIG = load_scoring_config()


@pytest.fixture(scope="module")
def snapshot():
    return load_fixture_json(BITBANK_FIXTURE)["results"]


def _parse(snapshot, tf, config=CONFIG):
    return parse_technicals(tf, snapshot[f"indicators_{tf}"], config)


def test_parse_daily_reads_numbers_not_labels(snapshot):
    t = _parse(snapshot, "1day")

    assert t.close == 10344652
    assert t.last_bar_date == date(2026, 11, 17)  # 形成中の足（11/17 9:00 開始）
    assert t.sma == {25: 11863830.32, 75: 12519897.07, 200: 11574749.52}
    assert t.rsi == 25.61
    assert t.bb_sigma == pytest.approx(-1.7609, abs=1e-4)
    assert (t.tenkan, t.kijun) == (10949567, 11426692)
    assert (t.macd_line, t.macd_signal) == (-591219.77, -431444.51)
    assert t.provisional is True


def test_cloud_uses_spans_computed_shift_bars_ago(snapshot):
    """ICHIMOKU_spanA は「今の足で計算した26本先の雲」。今の足の雲は26本前に計算した値"""
    raw = snapshot["indicators_1day"]["data"]["indicators"]
    t = _parse(snapshot, "1day")

    assert t.cloud_a == raw["ichi_series"]["spanA"][-27] == 13075957.25
    assert t.cloud_b == raw["ichi_series"]["spanB"][-27] == 12701391
    assert t.cloud_a != raw["ICHIMOKU_spanA"]  # ずらす前の値は使わない
    assert t.past_close == 12742032  # 26本前の終値（遅行スパンの比較相手）


def test_rsi_history_is_last_seven_daily_bars(snapshot):
    history = _parse(snapshot, "1day").rsi_history

    assert [d for d, _ in history] == [date(2026, 11, d) for d in range(11, 18)]
    assert [v for _, v in history] == [38.54, 32.64, 27.06, 21.9, 26.46, 25.65, 25.61]


def test_monthly_sma200_is_not_available(snapshot):
    t = _parse(snapshot, "1month")

    assert t.sma[200] is None
    assert t.last_bar_date == date(2026, 11, 1)


@pytest.mark.parametrize(
    "tf,expected",
    [
        (
            "1day",
            ["雲の下", "三役逆転", "混在（75 > 25 > 200）", "25.6（売られすぎ）",
             "シグナルの下・0より下", "-1.76σ", -4, "弱気"],
        ),
        (
            "1week",
            ["雲の下", "なし（強気 1/3）", "混在（75 > 25 > 200）", "39.0（弱め）",
             "シグナルの下・0より下", "-1.13σ", -3, "弱気"],
        ),
        (
            "1month",
            ["雲の上", "なし（強気 2/3）", "上昇の並び（25 > 75）（200本は算出不可）", "45.5（中立）",
             "シグナルの下・0より上", "-1.19σ", 1, "中立"],
        ),
    ],
)  # fmt: skip
def test_assessment_from_real_snapshot(snapshot, tf, expected):
    a = assess(_parse(snapshot, tf), CONFIG)

    assert [
        a.cloud.label, a.sanyaku.label, a.ma_order.label, a.rsi.label,
        a.macd.label, a.bb, a.total, a.verdict,
    ] == expected  # fmt: skip


@pytest.mark.parametrize(
    "value,zone",
    [
        (30, "売られすぎ"), (30.01, "弱め"), (44.99, "弱め"), (45, "中立"), (55, "中立"),
        (55.01, "強め"), (69.99, "強め"), (70, "買われすぎ"),
    ],
)  # fmt: skip
def test_rsi_zone_boundaries(value, zone):
    """30以下 売られすぎ／30〜45 弱め／45〜55 中立／55〜70 強め／70以上 買われすぎ"""
    assert rsi_zone(value, CONFIG)[1] == zone


def test_rsi_scores_follow_config(snapshot):
    """売られすぎを「反発の余地」と見る設定にすると、点数が変わる"""
    config = ScoringConfig(rsi={"scores": {"oversold": 1}})

    a = assess(_parse(snapshot, "1day", config), config)

    assert a.rsi.score == 1
    assert a.total == -2  # -4 から +2


def test_ma_order_partial_can_be_disabled(snapshot):
    config = ScoringConfig(moving_average={"allow_partial": False})

    signal = ma_order_signal(_parse(snapshot, "1month", config), config)

    assert (signal.label, signal.score) == ("算出不可（200本は算出不可）", 0)


def test_ma_order_perfect_orders(snapshot):
    t = _parse(snapshot, "1day")

    up = ma_order_signal(replace(t, sma={25: 3, 75: 2, 200: 1}), CONFIG)
    down = ma_order_signal(replace(t, sma={25: 1, 75: 2, 200: 3}), CONFIG)

    assert (up.label, up.score) == ("上昇の並び（25 > 75 > 200）", 1)
    assert (down.label, down.score) == ("下降の並び（200 > 75 > 25）", -1)


def test_cloud_and_sanyaku_edge_cases(snapshot):
    t = _parse(snapshot, "1day")

    inside = replace(t, close=12800000)  # 雲（12,701,391〜13,075,957）の中
    assert cloud_signal(inside).label == "雲の中"
    bullish = replace(t, close=14000000, tenkan=2, kijun=1, past_close=1)
    assert (sanyaku_signal(bullish).label, sanyaku_signal(bullish).score) == ("三役好転", 1)
    missing = replace(t, cloud_a=None)
    assert cloud_signal(missing).label == sanyaku_signal(missing).label == "算出不可"


def test_verdict_thresholds_follow_config(snapshot):
    config = ScoringConfig(judgement={"bullish_at": 5, "bearish_at": -5})

    assert assess(_parse(snapshot, "1day", config), config).verdict == "中立"


def test_shift_follows_config(snapshot):
    config = ScoringConfig(ichimoku={"shift": 25})
    raw = snapshot["indicators_1day"]["data"]["indicators"]

    assert _parse(snapshot, "1day", config).cloud_a == raw["ichi_series"]["spanA"][-26]


def test_unexpected_shape_raises():
    with pytest.raises(TechnicalsError):
        parse_technicals("1day", {"data": {}}, CONFIG)


def test_shipped_scoring_config_matches_spec():
    c = load_scoring_config()

    assert (c.judgement.bullish_at, c.judgement.bearish_at) == (2, -2)
    assert (c.rsi.oversold, c.rsi.weak, c.rsi.strong, c.rsi.overbought) == (30, 45, 55, 70)
    assert c.moving_average.periods == [25, 75, 200]
    assert c.ichimoku.shift == 26


@pytest.mark.parametrize(
    "bad",
    [
        {"rsi": {"weak": 25}},
        {"moving_average": {"periods": [25, 100]}},
        {"judgement": {"bullish_at": -2, "bearish_at": 2}},
    ],
)
def test_invalid_scoring_config_is_rejected(bad):
    with pytest.raises(ValueError):
        ScoringConfig(**bad)
