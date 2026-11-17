"""BTCの詳細・暗号資産ウォッチリストのセクションと、マーケット一覧の BTC/JPY 行

bitbank-lab-mcp には1回の実行で1度だけ接続し、結果を ctx.data に置いて3つの
セクション（マーケット一覧・BTCの詳細・暗号資産ウォッチリスト）で共有する。
接続に失敗したら、その失敗も覚えておき、後のセクションで再接続しない（待ち時間を増やさない）。
"""

import logging

from good_morning.collector import bitbank_mcp
from good_morning.collector.bitbank_mcp import TIMEFRAMES, BitbankSnapshot
from good_morning.context import RunContext, SectionContent
from good_morning.crypto.config import load_scoring_config
from good_morning.crypto.technicals import TIMEFRAME_LABELS, Assessment, assess, parse_technicals
from good_morning.crypto.tickers import CryptoTicker, format_price_text, parse_tickers
from good_morning.markets.quotes import Quote, QuoteFailure, QuoteResult
from good_morning.timeutil import format_jst, format_month_day

logger = logging.getLogger(__name__)

SOURCE_BITBANK = "bitbank（bitbank-lab-mcp）"
_SNAPSHOT_KEY = "_bitbank_snapshot"
FAILED = "取得失敗"


def get_snapshot(ctx: RunContext) -> BitbankSnapshot:
    """bitbank のデータを取得する（1回の実行で1度だけ。失敗も覚えておく）"""
    cached = ctx.data.get(_SNAPSHOT_KEY)
    if cached is None:
        try:
            cached = bitbank_mcp.fetch_snapshot(bitbank_mcp.snapshot_calls(_main_pair(ctx)))
        except Exception as e:  # noqa: BLE001 - 失敗を覚えて、各セクションで「取得失敗」にする
            logger.error("bitbank-lab-mcp: %s", e)
            cached = e
        ctx.data[_SNAPSHOT_KEY] = cached
    if isinstance(cached, Exception):
        raise cached
    return cached


def _main_pair(ctx: RunContext) -> str:
    return ctx.watchlist.crypto.main if ctx.watchlist else "btc_jpy"


def _tickers(ctx: RunContext) -> dict[str, CryptoTicker]:
    return parse_tickers(get_snapshot(ctx).get("tickers_jpy"))


def bitbank_basis_line(ctx: RunContext) -> str:
    return (
        f"BTC・暗号資産: bitbank の取得時点の値（{format_jst(ctx.now)}）。"
        "日足・週足・月足は形成中の足を含む"
    )


# --- マーケット一覧の BTC/JPY 行 --------------------------------------------


def btc_market_quote(ctx: RunContext) -> QuoteResult:
    """マーケット一覧の先頭に入れる BTC/JPY（前日比は24時間前との比較）"""
    pair = _main_pair(ctx)
    try:
        ticker = _tickers(ctx)[pair]
    except Exception as e:  # noqa: BLE001 - BTC の行だけ「取得失敗」にする
        logger.warning("BTC/JPY（マーケット一覧）: 取得失敗 - %s", e)
        return QuoteFailure(ticker=pair, name="BTC/JPY", reason=str(e))

    today = ctx.now.date()
    return Quote(
        ticker=pair,
        name=ticker.label,
        basis="live",
        format="price",
        decimals=0,
        last=ticker.last,
        prev=ticker.open,
        last_date=today,
        prev_date=today,
    )


# --- BTCの詳細 ----------------------------------------------------------------


def _assess_all(ctx: RunContext) -> dict[str, Assessment | Exception]:
    snapshot = get_snapshot(ctx)
    config = load_scoring_config()
    results: dict[str, Assessment | Exception] = {}
    for tf in TIMEFRAMES:
        try:
            technicals = parse_technicals(tf, snapshot.get(f"indicators_{tf}"), config)
            results[tf] = assess(technicals, config)
        except Exception as e:  # noqa: BLE001 - 時間軸ごとに「取得失敗」にする
            logger.warning("BTCの詳細 %s: 取得失敗 - %s", TIMEFRAME_LABELS[tf], e)
            results[tf] = e
    return results


def _cell(result: Assessment | Exception, render) -> str:
    return FAILED if isinstance(result, Exception) else render(result)


SCORE_MARKS = {1: "🟢", 0: "⚪", -1: "🔴"}
SCORE_LEGEND = "🟢 強気 +1・⚪ 中立 0・🔴 弱気 -1"


def _scored(signal) -> str:
    return f"{SCORE_MARKS[signal.score]} {signal.label}"


def render_btc_table(results: dict[str, Assessment | Exception], ma_periods: list[int]) -> str:
    rows = [
        ("一目：雲との位置", lambda a: _scored(a.cloud)),
        ("一目：三役", lambda a: _scored(a.sanyaku)),
        (f"移動平均の並び（{'/'.join(map(str, ma_periods))}本）", lambda a: _scored(a.ma_order)),
        ("ボリンジャーバンドのσ位置", lambda a: a.bb),
        ("RSI(14)", lambda a: _scored(a.rsi)),
        ("MACD", lambda a: _scored(a.macd)),
        ("判定", lambda a: f"**{a.verdict}**（{a.total:+d}）"),
    ]
    header = "| | " + " | ".join(TIMEFRAME_LABELS[tf] for tf in TIMEFRAMES) + " |"
    lines = [header, "|---|" + "---|" * len(TIMEFRAMES)]
    for label, render in rows:
        cells = " | ".join(_cell(results[tf], render) for tf in TIMEFRAMES)
        lines.append(f"| {label} | {cells} |")
    return "\n".join(lines)


def render_rsi_history(assessment: Assessment) -> str:
    history = assessment.technicals.rsi_history
    dates = [format_month_day(d) for d, _ in history]
    if dates:
        dates[-1] += "※"
    values = ["—" if v is None else f"{v:.1f}" for _, v in history]
    return "\n".join(
        [
            "| " + " | ".join(dates) + " |",
            "|" + "---:|" * len(dates),
            "| " + " | ".join(values) + " |",
        ]
    )


def build_btc(ctx: RunContext) -> SectionContent:
    results = _assess_all(ctx)
    if all(isinstance(r, Exception) for r in results.values()):
        raise next(iter(results.values()))
    ctx.data["btc_assessments"] = {
        tf: r for tf, r in results.items() if not isinstance(r, Exception)
    }

    body = []
    try:
        ticker = _tickers(ctx)[_main_pair(ctx)]
        body.append(
            f"**{ticker.label} {format_price_text(ticker.last_text)}円**"
            f"（24時間 {ticker.change_pct:+.2f}%）"
        )
        body.append("")
    except Exception as e:  # noqa: BLE001 - 価格の行が出せなくても表は出す
        logger.warning("BTCの詳細（価格）: 取得失敗 - %s", e)

    config = load_scoring_config()
    body.append(render_btc_table(results, config.moving_average.periods))
    body.append("")
    body.append(
        f"{SCORE_LEGEND}。5要素の合計が {config.judgement.bullish_at:+d} 以上で強気、"
        f"{config.judgement.bearish_at:+d} 以下で弱気（基準は config/scoring.yaml）。"
    )

    daily = results.get("1day")
    if isinstance(daily, Assessment) and daily.technicals.rsi_history:
        body.extend(["", "**日足 RSI(14) の推移**", "", render_rsi_history(daily)])

    body.extend(
        [
            "",
            (
                "※ 最新の足は形成中（途中経過）です。日足は毎日 9:00、週足は月曜 9:00、"
                "月足は1日 9:00（日本時間）に新しい足に切り替わります。"
            ),
            "",
            "> Claude による2〜3行のまとめは、フェーズ5で追加します。",
        ]
    )
    return SectionContent(
        body="\n".join(body), basis=[bitbank_basis_line(ctx)], sources=[SOURCE_BITBANK]
    )


# --- 暗号資産ウォッチリスト ----------------------------------------------------


def validate_pairs(pairs: list[str], available: dict[str, CryptoTicker]) -> tuple[list, list]:
    """取扱銘柄と照合する。(取扱あり, 取扱なし) を返す"""
    found = [p for p in pairs if p in available]
    missing = [p for p in pairs if p not in available]
    for pair in missing:
        logger.warning("暗号資産ウォッチリスト: %s は bitbank の取扱銘柄にないためスキップします", pair)
    return found, missing


def render_crypto_table(btc: CryptoTicker, rows: list[CryptoTicker]) -> str:
    lines = ["| 銘柄 | 価格（円） | 24時間 | 対BTC |", "|---|---:|---:|---:|"]
    lines.append(
        f"| {btc.label}（基準） | {format_price_text(btc.last_text)} | {btc.change_pct:+.2f}% | — |"
    )
    for t in rows:
        diff = t.change_pct - btc.change_pct
        lines.append(
            f"| {t.label} | {format_price_text(t.last_text)} | {t.change_pct:+.2f}% "
            f"| {diff:+.2f}pt |"
        )
    return "\n".join(lines)


def build_crypto_watchlist(ctx: RunContext) -> SectionContent:
    if ctx.watchlist is None:
        raise ValueError("ウォッチリストを読み込めていません")

    tickers = _tickers(ctx)
    main = _main_pair(ctx)
    if main not in tickers:
        raise ValueError(f"メイン銘柄 {main} が bitbank の取扱銘柄にありません")

    found, missing = validate_pairs(ctx.watchlist.crypto.watch, tickers)
    rows = [tickers[p] for p in found]
    ctx.data["crypto_watchlist"] = {"btc": tickers[main], "rows": rows}

    body = [render_crypto_table(tickers[main], rows), ""]
    body.append("対BTC: 24時間の変化率の BTC との差（プラスなら BTC より強い）。単位は %pt。")
    if missing:
        body.append(f"⚠ bitbank の取扱銘柄にないためスキップ: {', '.join(missing)}")
    return SectionContent(
        body="\n".join(body), basis=[bitbank_basis_line(ctx)], sources=[SOURCE_BITBANK]
    )
