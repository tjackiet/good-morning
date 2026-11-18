"""グラフの部品（ビューモデルの数値から、決まった形で描く）

色はテンプレートの CSS 変数（--up / --down / --neutral など）で決め、ここでは形だけを作る。
- 増減の棒（diverging bar）: 中央を0に、上がりは右へ青、下がりは左へ赤。幅は最大の絶対値に合わせる。
- RSI の線グラフ: 2px の線、30 と 70 の目安線、最新の点に値を添える（グラフのガイドの決まり）。
"""

import math
from html import escape


def add_bar_widths(rows: list[dict] | None, key: str = "pct", max_width: float = 100.0) -> list[dict]:
    """各行に bar（0〜100: 片側の幅に対する割合）と dir（1 / -1 / 0）を足した新しいリストを返す"""
    rows = rows or []
    values = [abs(r[key]) for r in rows if not r.get("failed") and r.get(key) is not None]
    scale = max(values) if values else 0
    result = []
    for r in rows:
        r = dict(r)
        value = r.get(key)
        if r.get("failed") or value is None or scale == 0:
            r["bar"], r["dir"] = 0.0, 0
        else:
            r["bar"] = round(abs(value) / scale * max_width, 2)
            r["dir"] = (value > 0) - (value < 0)
        result.append(r)
    return result


def rsi_domain(values: list[float], oversold: float, overbought: float) -> tuple[float, float]:
    """縦軸の範囲。目安線（30・70）とデータが入る範囲を、10刻みで少し余裕を持たせて決める"""
    low = min([*values, oversold]) - 5
    high = max([*values, overbought]) + 5
    return max(0.0, math.floor(low / 10) * 10), min(100.0, math.ceil(high / 10) * 10)


def rsi_svg(history: list[dict], oversold: float = 30, overbought: float = 70) -> str:
    """日足 RSI の推移の SVG（値は history の数値をそのまま使う）"""
    if not history:
        return ""
    width, height = 340, 176
    left, right, top, bottom = 30, 46, 10, 26
    plot_w, plot_h = width - left - right, height - top - bottom
    lo, hi = rsi_domain([p["value"] for p in history], oversold, overbought)

    def x(i: int) -> float:
        return left + (plot_w * i / (len(history) - 1) if len(history) > 1 else plot_w / 2)

    def y(v: float) -> float:
        return top + plot_h * (1 - (v - lo) / (hi - lo))

    parts = [
        (
            f'<svg class="rsi" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="日足 RSI(14) の直近{len(history)}本の推移">'
        )
    ]
    # 買われすぎ（70以上）・売られすぎ（30以下）の帯は、方向の色ではなく灰色の薄い帯で示す
    parts.append(
        f'<rect class="zone" x="{left}" y="{top}" width="{plot_w}" height="{max(0.0, y(overbought) - top):.1f}"/>'
    )
    parts.append(
        f'<rect class="zone" x="{left}" y="{y(oversold):.1f}" width="{plot_w}" '
        f'height="{max(0.0, top + plot_h - y(oversold)):.1f}"/>'
    )
    for level in (overbought, 50, oversold):
        yy = y(level)
        parts.append(f'<line class="grid" x1="{left}" x2="{left + plot_w}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="axis" x="{left - 6}" y="{yy + 4:.1f}" text-anchor="end">{level:g}</text>')
    # 日付（最初・真ん中・最後だけ。全部に付けると混む）
    picks = sorted({0, len(history) // 2, len(history) - 1})
    for i in picks:
        parts.append(
            f'<text class="axis" x="{x(i):.1f}" y="{height - 6}" text-anchor="middle">{escape(history[i]["date"])}</text>'
        )
    points = " ".join(f"{x(i):.1f},{y(p['value']):.1f}" for i, p in enumerate(history))
    parts.append(f'<polyline class="line" points="{points}"/>')
    # 各点のホバー（当たり判定は点より大きく）と、最新の点
    for i, p in enumerate(history):
        parts.append(
            f'<circle class="hit" cx="{x(i):.1f}" cy="{y(p["value"]):.1f}" r="10">'
            f'<title>{escape(p["date"])} RSI {p["value"]:.1f}</title></circle>'
        )
    last = history[-1]
    lx, ly = x(len(history) - 1), y(last["value"])
    parts.append(f'<circle class="dot" cx="{lx:.1f}" cy="{ly:.1f}" r="4"/>')
    parts.append(f'<text class="end-label" x="{lx + 8:.1f}" y="{ly + 4:.1f}">{last["value"]:.1f}</text>')
    parts.append("</svg>")
    return "".join(parts)
