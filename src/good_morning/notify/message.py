"""通知に載せる短いメッセージ

保存したビューモデル（outputs/YYYY-MM-DD.json）から作る。数値はビューモデルの計算済みの値と、
照合済みの Claude のまとめだけを使う（大原則1）。画像のカードを添付するときは、カードに
同じ内容が載るので、文章は判定とリンクだけにする（通知のプレビューで判定が見えるように）。
"""

STANCE_MARKS = {"リスクオン": "🟢", "様子見": "⚪", "リスクオフ": "🔴"}


def build_notification(
    view: dict, link: str | None, report_path: str, with_image: bool = False
) -> str:
    lines = [f"**🌅 モーニングレター {view.get('date_label', '')}**"]

    summary = view.get("summary")
    if summary:
        lines.append(f"判定: {STANCE_MARKS.get(summary['stance'], '')} **{summary['stance']}**")
        if not with_image:
            lines.extend(f"{i}. {line}" for i, line in enumerate(summary["lines"], 1))
    else:
        lines.append("（今朝のまとめは作成できませんでした）")

    if not with_image:
        parts = []
        hero = (view.get("markets") or {}).get("hero")
        if hero and not hero.get("failed"):
            parts.append(f"{hero['name']} {hero['value']}円（24時間 {hero['pct_label']}）")
        timeframes = (view.get("btc") or {}).get("timeframes") or []
        if timeframes:
            daily = timeframes[0]
            parts.append(f"{daily['label']} {daily['verdict']}（{daily['total']:+d}）")
        if parts:
            lines.append("・".join(parts))
        etf = (view.get("etf") or {}).get("total")
        if etf:
            lines.append(f"BTC 現物ETF の純流入（{view['etf']['date_short']}）: {etf['label']}百万ドル")

    failed = view.get("failed_sections") or []
    if failed:
        lines.append(f"⚠ 取得失敗: {'、'.join(failed)}")

    if link:
        lines.append(f"[レポートを開く]({link})")
    else:
        lines.append(f"レポート: {report_path}（このMacに保存）")
    return "\n".join(lines)
