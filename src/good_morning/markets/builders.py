"""マーケット一覧・セクター別騰落率・株式ウォッチリストのセクションを作る

銘柄ごとに取得し、失敗した銘柄はその行だけ「取得失敗」にして続ける（理由はログ）。
すべての銘柄で失敗したときは例外を投げ、セクション全体を「取得失敗」にする。
"""

import logging

from good_morning.collector.market_data import MarketDataError, fetch_daily_series
from good_morning.context import RunContext, SectionContent
from good_morning.markets.config import MarketClose, load_markets_config
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
    results = [
        fetch_quote(
            m.ticker,
            m.name,
            ctx,
            close,
            basis=m.basis,
            value_format=m.format,
            decimals=m.decimals,
        )
        for m in config.enabled_markets()
    ]
    _ensure_some_succeeded(results, "マーケット一覧")
    ctx.data["markets"] = results

    body = [render_market_table(results, common_close_date(results)), ""]
    if any(isinstance(r, Quote) and r.basis == "live" for r in results):
        body.append(
            f"{LIVE_MARK} 取得時点の値（ほぼ24時間取引される為替・先物など）。"
            "前日比は前日の足の終値との比較です。"
        )
    body.append("BTC/JPY（bitbank）はフェーズ2で追加します。")
    return SectionContent(
        body="\n".join(body),
        basis=_basis_lines(results, ctx, close),
        sources=[SOURCE_YFINANCE],
    )


def build_sectors(ctx: RunContext) -> SectionContent:
    config = load_markets_config()
    close = config.us_market_close
    results = [fetch_quote(s.ticker, s.name, ctx, close) for s in config.sectors]
    _ensure_some_succeeded(results, "セクター別騰落率")
    ranked = sort_by_change_pct(results)
    ctx.data["sectors"] = ranked

    return SectionContent(
        body=render_sector_table(ranked, common_close_date(ranked)),
        basis=_basis_lines(ranked, ctx, close),
        sources=[SOURCE_YFINANCE],
    )


def build_stock_watchlist(ctx: RunContext) -> SectionContent:
    if ctx.watchlist is None:
        raise ValueError("ウォッチリストを読み込めていません")
    if not ctx.watchlist.stocks:
        return SectionContent(body="ウォッチリストに米国株が登録されていません。")

    close = load_markets_config().us_market_close
    results = [fetch_quote(s.ticker, s.name, ctx, close) for s in ctx.watchlist.stocks]
    _ensure_some_succeeded(results, "株式ウォッチリスト")
    ranked = sort_by_change_pct(results)
    ctx.data["stock_watchlist"] = ranked

    return SectionContent(
        body=render_stock_table(ranked, common_close_date(ranked)) + "\n\n単位: ドル",
        basis=_basis_lines(ranked, ctx, close),
        sources=[SOURCE_YFINANCE],
    )
