"""通知に載せる短いメッセージ（判定・3行の要約・BTC・リンク）

数値は ctx.data の計算済みの値と、照合済みの Claude のまとめだけを使う（大原則1）。
"""

from good_morning.context import RunContext
from good_morning.crypto.tickers import format_price_text
from good_morning.reporter.markdown import STATUS_FAILED, Section
from good_morning.synthesis.builders import STANCE_MARKS
from good_morning.synthesis.claude import Synthesis
from good_morning.timeutil import format_month_day


def build_notification(
    ctx: RunContext, sections: list[Section], link: str | None, report_path: str
) -> str:
    lines = [f"**🌅 モーニングレター {format_month_day(ctx.now)}**"]

    synthesis = ctx.data.get("synthesis")
    if isinstance(synthesis, Synthesis):
        lines.append(f"判定: {STANCE_MARKS[synthesis.stance]} **{synthesis.stance}**")
        lines.extend(f"{i}. {line}" for i, line in enumerate(synthesis.summary_lines, 1))
    else:
        lines.append("（今朝のまとめは作成できませんでした）")

    btc_parts = []
    watch = ctx.data.get("crypto_watchlist")
    if watch:
        btc = watch["btc"]
        btc_parts.append(f"{btc.label} {format_price_text(btc.last_text)}円（24時間 {btc.change_pct:+.2f}%）")
    daily = (ctx.data.get("btc_assessments") or {}).get("1day")
    if daily is not None:
        btc_parts.append(f"日足 {daily.verdict}（{daily.total:+d}）")
    if btc_parts:
        lines.append("・".join(btc_parts))

    failed = [s.title for s in sections if s.status == STATUS_FAILED]
    if failed:
        lines.append(f"⚠ 取得失敗: {'、'.join(failed)}")

    if link:
        lines.append(f"[レポートを開く]({link})")
    else:
        lines.append(f"レポート: {report_path}（このMacに保存）")
    return "\n".join(lines)
