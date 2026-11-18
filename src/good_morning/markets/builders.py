"""マーケット一覧・セクター別騰落率・株式ウォッチリストのセクションを作る

銘柄ごとに取得し、失敗した銘柄はその行だけ「取得失敗」にして続ける（理由はログ）。
すべての銘柄で失敗したときは例外を投げ、セクション全体を「取得失敗」にする。
"""

import logging
import time

from good_morning.collector.market_data import MarketDataError, fetch_daily_series
from good_morning.context import RunContext, SectionContent
from good_morning.crypto.builders import SOURCE_BITBANK, bitbank_basis_line, btc_market_quote
from good_morning.markets.config import MarketClose, MissingCloseRetry, load_markets_config
from good_morning.markets.quotes import (
    Quote,
    QuoteFailure,
    QuoteResult,
    common_close_date,
    make_quote,
    sort_by_change_pct,
)
from good_morning.markets.tables import (
    LIVE_MARK,
    close_basis_line,
    live_basis_line,
    render_market_table,
    render_sector_table,
    render_stock_table,
    stale_note,
)

logger = logging.getLogger(__name__)

SOURCE_YFINANCE = "Yahoo Finance（yfinance）"


def fetch_quote(
    ticker: str,
    name: str,
    ctx: RunContext,
    close: MarketClose,
    *,
    basis="close",
    value_format="price",
    decimals: int = 2,
) -> QuoteResult:
    """1銘柄を取得して Quote にする。失敗したら QuoteFailure を返す（例外は投げない）"""
    try:
        series = fetch_daily_series(ticker)
        return make_quote(
            series,
            name=name,
            basis=basis,
            now=ctx.now,
            close=close,
            value_format=value_format,
            decimals=decimals,
        )
    except Exception as e:  # noqa: BLE001 - 1銘柄の失敗で表全体を止めない（大原則3）
        logger.warning("%s（%s）: 取得失敗 - %s", name, ticker, e)
        return QuoteFailure(ticker=ticker, name=name, reason=str(e))


# テストで待たずに済むよう、待つ関数を差し替えられるようにしておく
_sleep = time.sleep


def fetch_quotes(
    items: list[dict], ctx: RunContext, close: MarketClose, retry: MissingCloseRetry
) -> list[QuoteResult]:
    """複数の銘柄を取得する。確定しているはずの日の終値が空だった銘柄だけを、まとめて取り直す

    items は fetch_quote に渡す引数（ticker・name・basis・value_format・decimals）の辞書のリスト。
    """
    results = [fetch_quote(ctx=ctx, close=close, **item) for item in items]
    for attempt in range(1, retry.attempts + 1):
        stale = [i for i, r in enumerate(results) if isinstance(r, Quote) and r.missing_close]
        if not stale:
            break
        names = "、".join(items[i]["name"] for i in stale)
        logger.warning(
            "最新の終値が空の銘柄があるため %.0f 秒後に取り直します（%d/%d回目）: %s",
            retry.wait_seconds, attempt, retry.attempts, names,
        )
        _sleep(retry.wait_seconds)
        for i in stale:
            again = fetch_quote(ctx=ctx, close=close, **items[i])
            if isinstance(again, Quote):  # 取り直しで失敗したら、前の結果（注記付き）を残す
                results[i] = again
    still = [items[i]["name"] for i, r in enumerate(results) if isinstance(r, Quote) and r.missing_close]
    if still:
        logger.warning("取り直しても最新の終値が空のままの銘柄: %s", "、".join(still))
    return results


def _with_stale_note(body: str, results: list[QuoteResult]) -> str:
    note = stale_note(results)
    return f"{body}\n\n{note}" if note else body


def _ensure_some_succeeded(results: list[QuoteResult], label: str) -> None:
    if results and not any(isinstance(r, Quote) for r in results):
        raise MarketDataError(f"{label}: すべての銘柄で取得に失敗しました")


def _basis_lines(results: list[QuoteResult], ctx: RunContext, close: MarketClose) -> list[str]:
    lines = []
    base_date = common_close_date(results)
    if base_date is not None:
        lines.append(close_basis_line(base_date, close))
    if any(isinstance(r, Quote) and r.basis == "live" for r in results):
        lines.append(live_basis_line(ctx.now))
    return lines


def build_markets(ctx: RunContext) -> SectionContent:
    config = load_markets_config()
    close = config.us_market_close
    # 先頭は BTC/JPY（bitbank の取得時点の値。前日比は24時間前との比較）
    btc = btc_market_quote(ctx)
    items = [
        {"ticker": m.ticker, "name": m.name, "basis": m.basis, "value_format": m.format,
         "decimals": m.decimals}
        for m in config.enabled_markets()
    ]
    results = [btc] + fetch_quotes(items, ctx, close, config.missing_close_retry)
    _ensure_some_succeeded(results, "マーケット一覧")
    ctx.data["markets"] = results

    body = [render_market_table(results, common_close_date(results)), ""]
    if any(isinstance(r, Quote) and r.basis == "live" for r in results):
        body.append(
            f"{LIVE_MARK} 取得時点の値（ほぼ24時間取引される暗号資産・為替・先物など）。"
            "前日比は前日の足の終値との比較で、BTC/JPY のみ24時間前との比較です。"
        )
    if note := stale_note(results):
        body.append(note)

    basis = _basis_lines(results[1:], ctx, close)
    sources = [SOURCE_YFINANCE]
    if isinstance(btc, Quote):
        basis.insert(0, bitbank_basis_line(ctx))
        sources.insert(0, SOURCE_BITBANK)
    return SectionContent(body="\n".join(body), basis=basis, sources=sources)


def build_sectors(ctx: RunContext) -> SectionContent:
    config = load_markets_config()
    close = config.us_market_close
    items = [{"ticker": s.ticker, "name": s.name} for s in config.sectors]
    results = fetch_quotes(items, ctx, close, config.missing_close_retry)
    _ensure_some_succeeded(results, "セクター別騰落率")
    ranked = sort_by_change_pct(results)
    ctx.data["sectors"] = ranked

    return SectionContent(
        body=_with_stale_note(render_sector_table(ranked, common_close_date(ranked)), ranked),
        basis=_basis_lines(ranked, ctx, close),
        sources=[SOURCE_YFINANCE],
    )


def build_stock_watchlist(ctx: RunContext) -> SectionContent:
    if ctx.watchlist is None:
        raise ValueError("ウォッチリストを読み込めていません")
    if not ctx.watchlist.stocks:
        return SectionContent(body="ウォッチリストに米国株が登録されていません。")

    config = load_markets_config()
    close = config.us_market_close
    items = [{"ticker": s.ticker, "name": s.name} for s in ctx.watchlist.stocks]
    results = fetch_quotes(items, ctx, close, config.missing_close_retry)
    _ensure_some_succeeded(results, "株式ウォッチリスト")
    ranked = sort_by_change_pct(results)
    ctx.data["stock_watchlist"] = ranked

    table = render_stock_table(ranked, common_close_date(ranked)) + "\n\n単位: ドル"
    return SectionContent(
        body=_with_stale_note(table, ranked),
        basis=_basis_lines(ranked, ctx, close),
        sources=[SOURCE_YFINANCE],
    )
