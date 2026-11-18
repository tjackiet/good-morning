"""「今朝のまとめ」「暗号資産への示唆」のセクションと、BTCの詳細へのまとめの追記"""

from good_morning.context import RunContext, SectionContent
from good_morning.reporter.markdown import STATUS_OK, Section
from good_morning.synthesis.claude import Synthesis, get_synthesis

SOURCE_CLAUDE = "Claude（まとめ・示唆）"
STANCE_MARKS = {"リスクオン": "🟢", "様子見": "⚪", "リスクオフ": "🔴"}
NUMBERS_NOTE = "（Claude がこのレポートの数値から作成。文中の数値は元データと機械的に照合済み）"


def _unverified_note(s: Synthesis) -> list[str]:
    if not s.unverified_numbers:
        return []
    return ["", f"⚠ 次の数値は元データで確認できませんでした: {', '.join(s.unverified_numbers)}"]


def build_summary(ctx: RunContext) -> SectionContent:
    s = get_synthesis(ctx)
    body = [f"**判定: {STANCE_MARKS[s.stance]} {s.stance}**", ""]
    body.extend(f"{i}. {line}" for i, line in enumerate(s.summary_lines, 1))
    body.extend(["", NUMBERS_NOTE, *_unverified_note(s)])
    return SectionContent(body="\n".join(body), sources=[SOURCE_CLAUDE])


def build_implications(ctx: RunContext) -> SectionContent:
    s = get_synthesis(ctx)
    body = ["**強気材料**", ""]
    body.extend(f"- {item}" for item in s.bullish)
    body.extend(["", "**弱気材料**", ""])
    body.extend(f"- {item}" for item in s.bearish)
    body.extend(["", f"**まとめ**: {s.conclusion}", *_unverified_note(s)])
    return SectionContent(body="\n".join(body), sources=[SOURCE_CLAUDE])


def attach_btc_comment(sections: list[Section], ctx: RunContext) -> None:
    """まとめが作れていれば、BTCの詳細の末尾に Claude の2〜3行のまとめを足す"""
    synthesis = ctx.data.get("synthesis")
    if not isinstance(synthesis, Synthesis):
        return
    for section in sections:
        if section.key == "btc" and section.status == STATUS_OK:
            section.body = section.body.rstrip() + f"\n\n**まとめ（Claude）**: {synthesis.btc_comment}"
