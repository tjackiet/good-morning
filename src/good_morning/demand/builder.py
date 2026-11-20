"""暗号資産の需給のセクション（ステーブルコインの供給量・Coinbase プレミアム・日本プレミアム）

- ステーブルコイン: DefiLlama の日次の合計（ドル連動）の最新の値と、前日・N日前との差。内訳（USDT など）は
  銘柄ごとの取得時点の値と、前日・7日前の値との差。
- Coinbase プレミアム: (Coinbase BTC-USD ÷ Binance BTC-USDT − 1) × 100。2つは続けて取得する。
- 日本プレミアム: bitbank の BTC/JPY をドル円（マーケット一覧の JPY=X）でドルに換算し、
  (換算した値 ÷ Coinbase BTC-USD − 1) × 100。bitbank の価格は Coinbase・Binance と続けて公開 API から取る
  （取れなければ、マーケット一覧で bitbank-lab-mcp から取った少し前の値を使う）。価格の時刻を添える。

計算は取得した数値どうしの引き算・割り算だけ（大原則1）。ステーブルコインと2つのプレミアムは独立に扱い、
1つの失敗はその部分だけ「取得失敗」にする。全部失敗したらセクションごと「取得失敗」。
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from good_morning.collector import defillama, spot_prices
from good_morning.collector.defillama import CoinSupply, SupplyPoint
from good_morning.collector.spot_prices import SpotPrice
from good_morning.context import RunContext, SectionContent
from good_morning.demand.config import DemandConfig, load_demand_config
from good_morning.markets.quotes import Quote
from good_morning.timeutil import JST

logger = logging.getLogger(__name__)

SOURCES = ["DefiLlama（ステーブルコインの供給量）", "Coinbase・Binance（BTC の現物価格）"]
BITBANK_PAIR = "btc_jpy"
USDJPY_TICKER = "JPY=X"
# 見方（レポートとビジュアルの両方に、短く添える）
HOW_TO_READ = [
    ("ステーブルコイン", "増えていれば、暗号資産を買う待機資金が増えている"),
    ("Coinbase プレミアム", "プラスなら米国の買いが強い（マイナスなら弱い）"),
    ("日本プレミアム", "プラスなら国内の価格が海外より割高"),
]
PREMIUM_NOTE = "Coinbase プレミアムは Binance の USDT 建ての価格と比べるので、USDT とドルの差も含む。"


class DemandError(Exception):
    """需給のデータがひとつも取れなかった"""


@dataclass(frozen=True)
class StablecoinSupply:
    date: date  # 合計の最新の日（DefiLlama の日次。UTC の日付）
    total: float  # ドル
    day_change: float | None
    period_change: float | None
    period_days: int
    coins: list[CoinSupply] = field(default_factory=list)

    @property
    def period_change_pct(self) -> float | None:
        """N日の増減率（%）。プレミアムの表示（%）とそろえるため"""
        return change_pct(self.total, self.period_change)


def change_pct(current: float, change: float | None) -> float | None:
    """増減（change）を、増減の前の値に対する % にする（前の値 = current − change）"""
    if change is None or current - change == 0:
        return None
    return change / (current - change) * 100


def week_change(c: CoinSupply) -> float | None:
    return c.current - c.prev_week if c.prev_week is not None else None


@dataclass(frozen=True)
class Premium:
    name: str  # Coinbase プレミアム / 日本プレミアム
    pct: float  # %
    diff_usd: float  # 比べる側 − 基準（ドル）
    detail: str  # 比べた価格（表に出す文字列）


@dataclass(frozen=True)
class DemandData:
    stablecoins: StablecoinSupply | None
    coinbase: Premium | None
    japan: Premium | None
    times: list[str]  # 価格の時刻（日本時間）「bitbank 9:45:12」など
    problems: list[str]


# --- 表記 ----------------------------------------------------------------------------


def oku_label(usd: float) -> str:
    """供給量（ドル）→ 億ドル・整数（例 2,852）"""
    return f"{round(usd / 1e8):,d}"


def change_with_pct_label(current: float, usd: float | None) -> str:
    """増減を「-41.3（-1.44%）」の形で（億ドル・%）"""
    pct = change_pct(current, usd)
    return oku_change_label(usd) + (f"（{pct_label(pct)}）" if pct is not None else "")


def oku_change_label(usd: float | None) -> str:
    """増減（ドル）→ 億ドル・小数1桁（例 -10.3、+2.0、0.0）。なければ —"""
    if usd is None:
        return "—"
    value = round(usd / 1e8, 1)
    return "0.0" if value == 0 else f"{value:+,.1f}"


def pct_label(pct: float | None) -> str:
    if pct is None:
        return "—"
    value = round(pct, 2)
    return "0.00%" if value == 0 else f"{value:+.2f}%"


def usd_label(usd: float, signed: bool = False) -> str:
    value = round(usd)
    if signed:
        return "0ドル" if value == 0 else f"{value:+,d}ドル"
    return f"{value:,d}ドル"


def _clock(t: datetime) -> str:
    """日本時間の時刻（例 9:45:12）"""
    t = t.astimezone(JST)
    return f"{t.hour}:{t:%M:%S}"


# --- 計算（取得した数値の差と比だけ） ----------------------------------------------------


def stablecoin_supply(
    points: list[SupplyPoint], coins: dict[str, CoinSupply], config: DemandConfig
) -> StablecoinSupply:
    if not points:
        raise DemandError("ステーブルコインの合計がありません")
    by_date = {p.date: p.total for p in points}
    last = points[-1]
    days = config.stablecoins.change_days

    def change(back: int) -> float | None:
        before = by_date.get(last.date - timedelta(days=back))
        return None if before is None else last.total - before

    return StablecoinSupply(
        date=last.date,
        total=last.total,
        day_change=change(1),
        period_change=change(days),
        period_days=days,
        coins=[coins[s] for s in config.stablecoins.breakdown if s in coins],
    )


def pair_label(symbol: str) -> str:
    """BTCUSDT → BTC-USDT（表示用）"""
    return f"{symbol[:-4]}-{symbol[-4:]}" if symbol.endswith("USDT") and len(symbol) > 4 else symbol


def coinbase_premium(coinbase: SpotPrice, reference: SpotPrice) -> Premium:
    return Premium(
        name="Coinbase プレミアム",
        pct=(coinbase.price / reference.price - 1) * 100,
        diff_usd=coinbase.price - reference.price,
        detail=(
            f"Coinbase {coinbase.symbol} {usd_label(coinbase.price)}／"
            f"Binance {pair_label(reference.symbol)} {usd_label(reference.price)}"
        ),
    )


def japan_premium(btc_jpy: float, usdjpy: float, coinbase: SpotPrice) -> Premium:
    in_usd = btc_jpy / usdjpy
    return Premium(
        name="日本プレミアム",
        pct=(in_usd / coinbase.price - 1) * 100,
        diff_usd=in_usd - coinbase.price,
        detail=(
            f"bitbank BTC/JPY {round(btc_jpy):,d}円 ÷ ドル円 {usdjpy:.2f} = {usd_label(in_usd)}／"
            f"Coinbase {usd_label(coinbase.price)}"
        ),
    )


def _bitbank_btc(ctx: RunContext):
    """bitbank の BTC/JPY（マーケット一覧で bitbank-lab-mcp から取得したデータ。なければ None）"""
    from good_morning.crypto.builders import get_snapshot
    from good_morning.crypto.tickers import parse_tickers

    try:
        return parse_tickers(get_snapshot(ctx).get("tickers_jpy")).get(BITBANK_PAIR)
    except Exception as e:  # noqa: BLE001 - 日本プレミアムだけ「取得失敗」にする
        logger.warning("日本プレミアム: bitbank の BTC/JPY がありません - %s", e)
        return None


def _usdjpy(ctx: RunContext) -> float | None:
    for q in ctx.data.get("markets") or []:
        if isinstance(q, Quote) and q.ticker == USDJPY_TICKER:
            return q.last
    return None


# --- 取得 ----------------------------------------------------------------------------


def collect(ctx: RunContext, config: DemandConfig) -> DemandData:
    problems: list[str] = []

    stablecoins = None
    try:
        points = defillama.fetch_totals()
        try:
            coins = defillama.fetch_assets(config.stablecoins.breakdown)
        except defillama.DefiLlamaError as e:
            logger.warning("ステーブルコインの内訳を取得できませんでした: %s", e)
            coins, problems = {}, [*problems, "ステーブルコインの内訳"]
        stablecoins = stablecoin_supply(points, coins, config)
    except (defillama.DefiLlamaError, DemandError) as e:
        logger.warning("ステーブルコインの供給量を取得できませんでした: %s", e)
        problems.append("ステーブルコインの供給量")

    # bitbank・Binance・Coinbase は間を空けずに続けて取得する
    reference = coinbase = bitbank = None
    try:
        bitbank = spot_prices.fetch_bitbank(BITBANK_PAIR)
    except spot_prices.SpotPriceError as e:
        logger.warning("bitbank の価格を公開 API から取得できませんでした（少し前の値を使う）: %s", e)
    try:
        reference = spot_prices.fetch_binance(config.premium.reference_symbol)
    except spot_prices.SpotPriceError as e:
        logger.warning("Binance の価格を取得できませんでした: %s", e)
    try:
        coinbase = spot_prices.fetch_coinbase(config.premium.coinbase_product)
    except spot_prices.SpotPriceError as e:
        logger.warning("Coinbase の価格を取得できませんでした: %s", e)

    times = []
    cb_premium = jp_premium = None
    if coinbase and reference:
        cb_premium = coinbase_premium(coinbase, reference)
    else:
        problems.append("Coinbase プレミアム")

    if bitbank is None:  # 公開 API で取れなければ、マーケット一覧で取った少し前の値
        btc = _bitbank_btc(ctx)
        if btc is not None:
            bitbank = SpotPrice(venue="bitbank", symbol=BITBANK_PAIR, price=btc.last, time=btc.timestamp or ctx.now)
    usdjpy = _usdjpy(ctx)
    if coinbase and bitbank is not None and usdjpy:
        jp_premium = japan_premium(bitbank.price, usdjpy, coinbase)
        times.append(f"bitbank {_clock(bitbank.time)}")
    else:
        if usdjpy is None:
            logger.warning("日本プレミアム: ドル円（%s）がありません", USDJPY_TICKER)
        problems.append("日本プレミアム")
    if coinbase:
        times.append(f"Coinbase {_clock(coinbase.time)}")
    if reference:
        times.append(f"Binance {_clock(reference.time)}")

    if stablecoins is None and cb_premium is None and jp_premium is None:
        raise DemandError("ステーブルコイン・プレミアムとも取得できませんでした")
    return DemandData(stablecoins, cb_premium, jp_premium, times, problems)


# --- 表示 ----------------------------------------------------------------------------


def short_day(d: date) -> str:
    return f"{d.month}/{d.day}"


def render_body(data: DemandData) -> str:
    how = "。".join(f"{name}は{text}" for name, text in HOW_TO_READ)
    body = [f"見方: {how}。", "", "**ステーブルコインの供給量（ドル連動・単位は億ドル）**", ""]
    s = data.stablecoins
    if s:
        total = [oku_label(s.total), oku_change_label(s.day_change), change_with_pct_label(s.total, s.period_change)]
        body.extend(
            [
                f"| 銘柄 | 供給量 | 前日比 | {s.period_days}日の増減 |",
                "|---|---:|---:|---:|",
                "| 合計 | " + " | ".join(total) + " |",
            ]
        )
        for c in s.coins:
            day = c.current - c.prev_day if c.prev_day is not None else None
            # 内訳の増減は DefiLlama が返す7日前との比較（合計の日数の設定とは別）
            cells = [
                c.symbol,
                oku_label(c.current),
                oku_change_label(day),
                change_with_pct_label(c.current, week_change(c)),
            ]
            body.append("| " + " | ".join(cells) + " |")
        note = f"合計は DefiLlama の日次の値（最新は {short_day(s.date)} 分）。"
        if s.coins:
            note += "銘柄ごとは取得時点の値で、増減は前日・7日前との比較。"
        body.extend(["", note])
    else:
        body.append("取得失敗")

    body.extend(["", "**プレミアム（取得時点）**", ""])
    body.extend(["| 項目 | 差 | 比べた価格 |", "|---|---:|---|"])
    for name, p in (("Coinbase プレミアム", data.coinbase), ("日本プレミアム", data.japan)):
        if p:
            diff = f"{pct_label(p.pct)}（{usd_label(p.diff_usd, signed=True)}）"
            body.append(f"| {name} | {diff} | {p.detail} |")
        else:
            body.append(f"| {name} | 取得失敗 | — |")
    note = PREMIUM_NOTE
    if data.times:
        note += f"価格の時刻（日本時間）: {'・'.join(data.times)}。"
    body.extend(["", note])
    if data.problems:
        body.extend(["", f"⚠ 取得できませんでした（理由はログを参照）: {'、'.join(data.problems)}"])
    return "\n".join(body)


def basis_line(data: DemandData, now: datetime) -> str:
    parts = []
    if data.stablecoins:
        parts.append(f"ステーブルコインは DefiLlama の日次の値（{short_day(data.stablecoins.date)} 分）")
    if data.coinbase or data.japan:
        parts.append(f"プレミアムは取得時点の価格（{now.astimezone(JST):%Y-%m-%d %H:%M} JST ごろ）")
    return "暗号資産の需給: " + "、".join(parts)


def build_crypto_demand(ctx: RunContext) -> SectionContent:
    data = collect(ctx, load_demand_config())
    ctx.data["crypto_demand"] = data
    return SectionContent(
        body=render_body(data), basis=[basis_line(data, ctx.now)], sources=list(SOURCES)
    )
