"""Claude に渡す「計算済みの数値」の一覧を作る

大原則1: LLM に数値を作らせない。ここでは各セクションの builder が ctx.data に置いた
計算済みの値を、レポートの表と同じ表記の文字列にして並べるだけで、新しい計算はしない。
Claude の出力に出てきた数値は、この文章に含まれる数値と照合する（good_morning.synthesis.numbers）。
"""

from good_morning.context import RunContext
from good_morning.crypto.technicals import TIMEFRAME_LABELS
from good_morning.crypto.tickers import format_price_text
from good_morning.markets.quotes import Quote
from good_morning.markets.tables import format_change, format_change_pct, format_value
from good_morning.timeutil import format_jst, format_month_day

SECTOR_EDGE = 3  # セクターは上位・下位それぞれこの数だけ渡す
NEWS_SUMMARY_CHARS = 200


def _quote_line(q, label: str | None = None) -> str:
    name = label or q.name
    if not isinstance(q, Quote):
        return f"- {name}: 取得失敗"
    basis = "取得時点" if q.basis == "live" else f"{q.last_date.month}/{q.last_date.day} 終値"
    if q.missing_close is not None:
        basis += f"。{q.missing_close.month}/{q.missing_close.day} の終値は取得元に未反映"
    pct = format_change_pct(q)
    pct_text = "" if pct == "—" else f"、前日比% {pct}"
    return f"- {name}（{basis}）: {format_value(q)}、前日比 {format_change(q)}{pct_text}"


def _markets(ctx: RunContext) -> list[str]:
    rows = ctx.data.get("markets")
    if not rows:
        return []
    lines = ["## マーケット一覧（BTC/JPY の前日比は24時間前との比較）"]
    lines.extend(_quote_line(q) for q in rows)
    return lines


def _sectors(ctx: RunContext) -> list[str]:
    rows = [r for r in ctx.data.get("sectors", []) if isinstance(r, Quote)]
    if not rows:
        return []
    lines = [f"## 米国セクター別騰落率（上位{SECTOR_EDGE}・下位{SECTOR_EDGE}）"]
    picked = rows if len(rows) <= SECTOR_EDGE * 2 else rows[:SECTOR_EDGE] + rows[-SECTOR_EDGE:]
    lines.extend(f"- {q.name}（{q.ticker}）: {format_change_pct(q)}" for q in picked)
    return lines


def _btc(ctx: RunContext) -> list[str]:
    assessments = ctx.data.get("btc_assessments") or {}
    if not assessments:
        return []
    lines = ["## BTC のテクニカル判定（5要素を強気+1・弱気-1・中立0で合計。最新の足は形成中）"]
    for tf, a in assessments.items():
        lines.append(
            f"- {TIMEFRAME_LABELS[tf]}: 判定 {a.verdict}（{a.total:+d}）。雲との位置 {a.cloud.label}、"
            f"三役 {a.sanyaku.label}、移動平均の並び {a.ma_order.label}、RSI(14) {a.rsi.label}、"
            f"MACD {a.macd.label}、ボリンジャーバンド {a.bb}"
        )
    daily = assessments.get("1day")
    if daily is not None and daily.technicals.rsi_history:
        history = " → ".join(
            f"{d.month}/{d.day} {v:.1f}" for d, v in daily.technicals.rsi_history if v is not None
        )
        lines.append(f"- 日足 RSI(14) の推移: {history}")
    return lines


def _crypto_watchlist(ctx: RunContext) -> list[str]:
    data = ctx.data.get("crypto_watchlist")
    if not data:
        return []
    btc = data["btc"]
    lines = ["## 暗号資産（bitbank、24時間の変化率。対BTC は BTC の変化率との差）"]
    lines.append(f"- {btc.label}: {format_price_text(btc.last_text)}円、{btc.change_pct:+.2f}%")
    for t in data["rows"]:
        lines.append(
            f"- {t.label}: {format_price_text(t.last_text)}円、{t.change_pct:+.2f}%"
            f"（対BTC {t.change_pct - btc.change_pct:+.2f}pt）"
        )
    return lines


def _stocks(ctx: RunContext) -> list[str]:
    rows = ctx.data.get("stock_watchlist")
    if not rows:
        return []
    lines = ["## 米国株ウォッチリスト（ドル）"]
    lines.extend(_quote_line(q, f"{q.name}（{q.ticker}）") for q in rows)
    return lines


def _calendar(ctx: RunContext) -> list[str]:
    data = ctx.data.get("calendar")
    if not data:
        return []
    lines = ["## 今後7日の予定（日本時間）"]
    for e in data["detail"]:
        when = format_month_day(e.day) + (f" {e.when:%H:%M}" if e.when else "")
        extra = f"、予想 {e.forecast}" if e.forecast else ""
        lines.append(f"- {when} {e.title}（重要度 {e.importance}{extra}）")
    if not data["detail"]:
        lines.append("- 予定なし")
    important_later = [e for e in data["later"] if e.importance == "高"]
    if important_later:
        lines.append("## 8〜30日の重要な予定")
        lines.extend(f"- {format_month_day(e.day)} {e.title}" for e in important_later)
    return lines


def _news(ctx: RunContext) -> list[str]:
    articles = ctx.data.get("news")
    if not articles:
        return []
    lines = ["## 主要ニュース（見出しと要約）"]
    for a in articles:
        lines.append(f"- [{a.source}] {a.title}")
        if a.ai_summary:
            lines.append(f"  - 要約: {a.ai_summary[:NEWS_SUMMARY_CHARS]}")
        if a.crypto_implication:
            lines.append(f"  - 暗号資産への示唆: {a.crypto_implication[:NEWS_SUMMARY_CHARS]}")
    return lines


def build_facts(ctx: RunContext) -> str:
    """Claude に渡すデータの文章を作る（取得できたセクションの分だけ）"""
    lines = [f"# データ（{format_jst(ctx.now)} 時点。すべて計算済み）"]
    for part in (_markets, _sectors, _btc, _crypto_watchlist, _stocks, _calendar, _news):
        section = part(ctx)
        if section:
            lines.append("")
            lines.extend(section)
    return "\n".join(lines)
