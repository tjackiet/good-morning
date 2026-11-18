"""ビジュアルレポートに渡すデータ（ビューモデル）を作る

各セクションの builder が ctx.data に置いた計算済みの値を、表示用の文字列と、グラフを描くための
数値に並べ替えるだけで、新しい計算はしない（大原則1）。結果は JSON にして outputs/ に保存し、
HTML はこの JSON から描く（デザインを直すたびにデータを取り直さなくて済むように）。
"""

from good_morning.context import RunContext
from good_morning.crypto.technicals import TIMEFRAME_LABELS
from good_morning.crypto.tickers import format_price_text
from good_morning.markets.quotes import Quote, common_close_date
from good_morning.markets.tables import (
    date_note,
    format_change,
    format_change_pct,
    format_value,
    stale_note,
    uniform_stale,
)
from good_morning.reporter.markdown import (
    DISCLAIMER,
    STATUS_FAILED,
    STATUS_OK,
    ReportMeta,
    Section,
    format_report_date,
)
from good_morning.synthesis.claude import Synthesis
from good_morning.timeutil import format_jst, format_month_day

VIEW_VERSION = 1
SNIPPET_CHARS = 140
# マーケット一覧のうち、上のタイルに大きく出す項目（残りは表に出す）
TILE_TICKERS = ("^GSPC", "^IXIC", "JPY=X", "^TNX", "^VIX", "GC=F")


def split_label(label: str) -> tuple[str, str]:
    """判定のラベルを、表のセルに大きく出す見出しと、小さく添える補足に分ける

    例: "25.3（売られすぎ）" → ("25.3", "売られすぎ")、"混在（75 > 25 > 200）" → ("混在", "75 > 25 > 200")、
        "シグナルの下・0より下" → ("シグナルの下", "0より下")
    """
    if "（" in label and label.endswith("）"):
        main, rest = label.split("（", 1)
        return main, rest[:-1].replace("）（", "・")
    if "・" in label:
        main, detail = label.split("・", 1)
        return main, detail
    return label, ""


def _quote_view(q, base_date=None, skip_stale: bool = False) -> dict:
    if not isinstance(q, Quote):
        return {"name": q.name, "ticker": q.ticker, "failed": True}
    pct = None if q.format == "yield" else round(q.change_pct, 4)
    return {
        "name": q.name,
        "ticker": q.ticker,
        "failed": False,
        "value": format_value(q),
        "change": format_change(q),
        "pct": pct,  # 利回りは前日比% を出さない（前日比は bp）
        "pct_label": format_change_pct(q),
        "direction": (q.change > 0) - (q.change < 0),
        "live": q.basis == "live",
        "date_note": date_note(q, base_date, skip_stale),
    }


def _markets(ctx: RunContext) -> dict | None:
    rows = ctx.data.get("markets")
    if not rows:
        return None
    base = common_close_date(rows)
    skip = uniform_stale(rows[1:] if rows and isinstance(rows[0], Quote) and rows[0].basis == "live" else rows)
    views = [_quote_view(q, base, skip) for q in rows]
    hero = views[0] if views and views[0]["ticker"].endswith("_jpy") else None
    rest = views[1:] if hero else views
    tiles = [v for v in rest if v["ticker"] in TILE_TICKERS]
    tiles.sort(key=lambda v: TILE_TICKERS.index(v["ticker"]))
    return {"hero": hero, "tiles": tiles, "rows": rest, "note": stale_note(rows)}


def _sectors(ctx: RunContext) -> list[dict] | None:
    rows = ctx.data.get("sectors")
    if not rows:
        return None
    base = common_close_date(rows)
    skip = uniform_stale(rows)
    return [_quote_view(q, base, skip) for q in rows]


def _stocks(ctx: RunContext) -> list[dict] | None:
    rows = ctx.data.get("stock_watchlist")
    if not rows:
        return None
    base = common_close_date(rows)
    skip = uniform_stale(rows)
    return [_quote_view(q, base, skip) for q in rows]


def _btc(ctx: RunContext) -> dict | None:
    assessments = ctx.data.get("btc_assessments") or {}
    if not assessments:
        return None
    timeframes = []
    for tf, a in assessments.items():
        signals = [
            {"name": name, "label": s.label, "score": s.score, "main": split_label(s.label)[0],
             "detail": split_label(s.label)[1]}
            for name, s in (
                ("雲との位置", a.cloud),
                ("三役", a.sanyaku),
                ("移動平均", a.ma_order),
                ("RSI(14)", a.rsi),
                ("MACD", a.macd),
            )
        ]
        timeframes.append(
            {
                "label": TIMEFRAME_LABELS[tf],
                "verdict": a.verdict,
                "total": a.total,
                "bb": a.bb,
                "signals": signals,
            }
        )
    daily = assessments.get("1day")
    rsi_history = []
    if daily is not None:
        rsi_history = [
            {"date": f"{d.month}/{d.day}", "value": v}
            for d, v in daily.technicals.rsi_history
            if v is not None
        ]
    synthesis = ctx.data.get("synthesis")
    return {
        "timeframes": timeframes,
        "rsi_history": rsi_history,
        "comment": synthesis.btc_comment if isinstance(synthesis, Synthesis) else None,
    }


def _crypto(ctx: RunContext) -> dict | None:
    data = ctx.data.get("crypto_watchlist")
    if not data:
        return None
    btc = data["btc"]

    def row(t, vs_btc):
        return {
            "label": t.label,
            "price": format_price_text(t.last_text),
            "pct": round(t.change_pct, 4),
            "pct_label": f"{t.change_pct:+.2f}%",
            "vs_btc": None if vs_btc is None else round(vs_btc, 4),
            "vs_btc_label": None if vs_btc is None else f"{vs_btc:+.2f}pt",
        }

    return {
        "btc": row(btc, None),
        "rows": [row(t, t.change_pct - btc.change_pct) for t in data["rows"]],
    }


def _event_view(e) -> dict:
    return {
        "when": format_month_day(e.day) + (f" {e.when:%H:%M}" if e.when else ""),
        "title": e.title,
        "importance": e.importance,
        "forecast": e.forecast,
        "estimated": e.estimated,
        "note": e.note,
    }


def _result_view(r) -> dict:
    from good_morning.schedule.builder import eps_label, surprise_label

    pct = r.surprise_pct
    return {
        "when": f"{format_month_day(r.when.date())} {r.when:%H:%M}",
        "name": r.name,
        "importance": r.importance,
        "reported_label": eps_label(r.reported_eps),  # None なら取得元に未反映
        "estimate_label": eps_label(r.eps_estimate),
        "surprise_label": surprise_label(r),
        "direction": 0 if pct is None or round(pct, 1) == 0 else (1 if pct > 0 else -1),
    }


def _calendar(ctx: RunContext) -> dict | None:
    data = ctx.data.get("calendar")
    if not data:
        return None
    return {
        "recent": [_result_view(r) for r in data.get("recent", [])],
        "recent_hours": data.get("recent_hours"),
        "detail": [_event_view(e) for e in data["detail"]],
        "later": [_event_view(e) for e in data["later"]],
    }


def _news(ctx: RunContext) -> list[dict] | None:
    from good_morning.collector.rss import load_feeds_config
    from good_morning.news.builder import plain_text, snippet

    articles = ctx.data.get("news")
    if not articles:
        return None
    labels = {name: c.label for name, c in load_feeds_config().categories.items()}
    views = []
    for a in articles:
        views.append(
            {
                "title": a.title,
                "url": a.url,
                "source": a.source,
                "category": labels.get(a.category, a.category),
                "published": (
                    f"{format_month_day(a.published)} {a.published:%H:%M}" if a.published else None
                ),
                "summary": a.ai_summary,
                "implication": a.crypto_implication,
                "snippet": None if a.ai_summary else (snippet(plain_text(a.summary), SNIPPET_CHARS) or None),
            }
        )
    return views


def build_view(ctx: RunContext, sections: list[Section], meta: ReportMeta) -> dict:
    """ビジュアルレポートに渡すデータを作る（JSON にできる値だけ）"""
    synthesis = ctx.data.get("synthesis")
    summary = implications = None
    if isinstance(synthesis, Synthesis):
        summary = {
            "stance": synthesis.stance,
            "lines": list(synthesis.summary_lines),
            "unverified": list(synthesis.unverified_numbers),
        }
        implications = {
            "bullish": list(synthesis.bullish),
            "bearish": list(synthesis.bearish),
            "conclusion": synthesis.conclusion,
        }

    basis = list(dict.fromkeys(line for s in sections for line in s.basis))
    sources = list(dict.fromkeys(src for s in sections for src in s.sources))
    status = {s.key: s.status for s in sections}

    return {
        "version": VIEW_VERSION,
        "title": f"モーニングレター {format_report_date(meta.generated_at)}",
        "date_label": format_report_date(meta.generated_at),
        "generated_at": format_jst(meta.generated_at),
        "basis": basis,
        "notices": list(meta.notices),
        "status": status,
        "failed_sections": [s.title for s in sections if s.status == STATUS_FAILED],
        "summary": summary,
        "markets": _markets(ctx) if status.get("markets") == STATUS_OK else None,
        "sectors": _sectors(ctx) if status.get("sectors") == STATUS_OK else None,
        "btc": _btc(ctx) if status.get("btc") == STATUS_OK else None,
        "crypto": _crypto(ctx) if status.get("crypto_watchlist") == STATUS_OK else None,
        "stocks": _stocks(ctx) if status.get("stock_watchlist") == STATUS_OK else None,
        "calendar": _calendar(ctx) if status.get("calendar") == STATUS_OK else None,
        "news": _news(ctx) if status.get("news") == STATUS_OK else None,
        "implications": implications,
        "notes": {
            "sectors": stale_note(ctx.data.get("sectors") or []),
            "stocks": stale_note(ctx.data.get("stock_watchlist") or []),
        },
        "sources": sources,
        "disclaimer": DISCLAIMER,
    }
