"""グラフの部品（ビューモデルの数値から、決まった形で描く）

色はテンプレートの CSS 変数（--up / --down / --neutral など）で決め、ここでは形だけを作る。
- 増減の棒（diverging bar）: 中央を0に、上がりは右へ青、下がりは左へ赤。幅は最大の絶対値に合わせる。
- RSI の線グラフ: 2px の線、30 と 70 の目安線、最新の点に値を添える（グラフのガイドの決まり）。
- 資金流出入の縦棒: 0 の線から、流入は上へ緑、流出は下へ赤。棒の先だけ角を丸める（0 の線の側は四角）。
  日ごとの値を読むグラフなので、棒ごとに値を添える（5本程度なので混まない）。
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


def _split_day(label: str) -> tuple[str, str]:
    """「11/18（水）」→（"11/18", "水"）。曜日がなければ（label, ""）"""
    if "（" in label and label.endswith("）"):
        day, weekday = label[:-1].split("（", 1)
        return day, weekday
    return label, ""


def _column_path(x: float, w: float, y0: float, y1: float, radius: float = 4.0) -> str:
    """x〜x+w の棒。y0 が 0 の線の側（四角）、y1 が棒の先（角を丸める）"""
    r = min(radius, abs(y1 - y0), w / 2)
    if y1 < y0:  # 上向き（流入）
        return (
            f"M{x:.1f},{y0:.1f}V{y1 + r:.1f}Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f}"
            f"H{x + w - r:.1f}Q{x + w:.1f},{y1:.1f} {x + w:.1f},{y1 + r:.1f}V{y0:.1f}Z"
        )
    return (  # 下向き（流出）
        f"M{x:.1f},{y0:.1f}V{y1 - r:.1f}Q{x:.1f},{y1:.1f} {x + r:.1f},{y1:.1f}"
        f"H{x + w - r:.1f}Q{x + w:.1f},{y1:.1f} {x + w:.1f},{y1 - r:.1f}V{y0:.1f}Z"
    )


def flow_columns_svg(rows: list[dict], unit: str = "百万ドル") -> str:
    """日ごとの資金流出入の縦棒（rows: label「11/18（水）」・value（数値）・value_label（表記）、古い順）"""
    rows = [r for r in rows or [] if r.get("value") is not None]
    if not rows:
        return ""
    width, height = 340, 190
    left, right = 22, 8  # 左は 0 の線に添える「0」の分
    label_space = 16  # 棒の先に添える値の分
    date_space = 30  # 下の日付（2行）の分
    top = label_space
    bottom = height - date_space - label_space
    values = [r["value"] for r in rows]
    lo, hi = min(0.0, *values), max(0.0, *values)
    if hi == lo:
        hi = lo + 1.0

    def y(v: float) -> float:
        return top + (hi - v) / (hi - lo) * (bottom - top)

    slot = (width - left - right) / len(rows)
    bar_w = min(36.0, slot * 0.56)
    zero = y(0.0)
    parts = [
        (
            f'<svg class="flow" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="直近{len(rows)}営業日の合計の純流入（{escape(unit)}）">'
        )
    ]
    for i, r in enumerate(rows):
        cx = left + slot * (i + 0.5)
        value = r["value"]
        cls = "up" if value > 0 else "down" if value < 0 else "neutral"
        latest = " latest" if i == len(rows) - 1 else ""
        day, weekday = _split_day(str(r.get("label", "")))
        tip = f"{escape(str(r.get('label', '')))} {escape(str(r['value_label']))}{escape(unit)}"
        parts.append(f'<g class="col-g{latest}"><title>{tip}</title>')
        parts.append(f'<rect class="hit" x="{cx - slot / 2:.1f}" y="0" width="{slot:.1f}" height="{height}"/>')
        if value != 0:
            parts.append(f'<path class="col {cls}" d="{_column_path(cx - bar_w / 2, bar_w, zero, y(value))}"/>')
        # 値は棒の先に（流入は上、流出は下、0 は線の上）
        ly = y(value) - 5 if value >= 0 else y(value) + 13
        parts.append(
            f'<text class="val {cls}" x="{cx:.1f}" y="{ly:.1f}" text-anchor="middle">{escape(str(r["value_label"]))}</text>'
        )
        parts.append(f'<text class="date" x="{cx:.1f}" y="{height - 16}" text-anchor="middle">{escape(day)}</text>')
        if weekday:
            parts.append(
                f'<text class="date wd" x="{cx:.1f}" y="{height - 3}" text-anchor="middle">{escape(weekday)}</text>'
            )
        parts.append("</g>")
    # 0 の線は棒の上に重ねて描き、左端に「0」を添える（流入・流出の境目が分かるように）
    parts.append(f'<line class="baseline" x1="{left - 2}" x2="{width - right}" y1="{zero:.1f}" y2="{zero:.1f}"/>')
    parts.append(f'<text class="zero" x="{left - 6}" y="{zero + 3.5:.1f}" text-anchor="end">0</text>')
    parts.append("</svg>")
    return "".join(parts)
