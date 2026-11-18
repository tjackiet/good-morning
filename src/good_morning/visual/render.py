"""ビューモデル（JSON）から、ビジュアルレポートの HTML を作る

テンプレートは Jinja2（自動エスケープあり）。ニュースの見出しなど外から来る文字は、
HTML として解釈されないようエスケープされる。リンクは http(s) のものだけを使う。
"""

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from good_morning.crypto.config import load_scoring_config
from good_morning.paths import OUTPUTS_DIR
from good_morning.visual.charts import add_bar_widths, rsi_svg
from good_morning.visual.viewmodel import split_label

TEMPLATE_DIR = Path(__file__).parent / "templates"
STANCE = {
    "リスクオン": {"cls": "up", "icon": "▲"},
    "様子見": {"cls": "neutral", "icon": "●"},
    "リスクオフ": {"cls": "down", "icon": "▼"},
}
VERDICT = {
    "強気": {"cls": "up", "icon": "▲"},
    "中立": {"cls": "neutral", "icon": "●"},
    "弱気": {"cls": "down", "icon": "▼"},
}
SCORE = {1: {"cls": "up", "icon": "▲"}, 0: {"cls": "neutral", "icon": "●"}, -1: {"cls": "down", "icon": "▼"}}


def safe_url(url: str | None) -> str:
    """http(s) の URL だけを通す（javascript: などのリンクを作らない）"""
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        return url
    return ""


def direction_class(value) -> str:
    if value is None:
        return "neutral"
    return "up" if value > 0 else "down" if value < 0 else "neutral"


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["safe_url"] = safe_url
    env.filters["dir"] = direction_class
    env.filters["bars"] = add_bar_widths
    env.globals.update(STANCE=STANCE, VERDICT=VERDICT, SCORE=SCORE)
    return env


def upgrade_view(view: dict) -> dict:
    """古い形式で保存したデータに、あとから足した項目を補う（保存済みの日も描けるように）"""
    for tf in (view.get("btc") or {}).get("timeframes", []):
        for sg in tf.get("signals", []):
            if "main" not in sg:
                sg["main"], sg["detail"] = split_label(sg["label"])
            if sg.get("name") == "移動平均の並び":
                sg["name"] = "移動平均"
    return view


def render_html(view: dict, standalone: bool = True) -> str:
    """standalone=False で、claude.ai のアーティファクトに公開する用の HTML（doctype などを付けない）を作る"""
    view = upgrade_view(view)
    rsi_config = load_scoring_config().rsi
    btc = view.get("btc") or {}
    chart = rsi_svg(btc.get("rsi_history") or [], rsi_config.oversold, rsi_config.overbought)
    template = _environment().get_template("report.html.j2")
    # rsi_svg は数値と、エスケープ済みの日付だけで作った SVG なので、そのまま埋め込む
    return template.render(v=view, rsi_chart=Markup(chart), standalone=standalone)


def view_path(day: str, outputs_dir: Path | None = None) -> Path:
    return (outputs_dir or OUTPUTS_DIR) / f"{day}.json"


def html_path(day: str, outputs_dir: Path | None = None) -> Path:
    return (outputs_dir or OUTPUTS_DIR) / f"{day}.html"


def artifact_path(day: str, outputs_dir: Path | None = None) -> Path:
    """claude.ai のアーティファクトに公開する用の HTML の保存先"""
    return (outputs_dir or OUTPUTS_DIR) / f"{day}-artifact.html"


def save_view(view: dict, day: str, outputs_dir: Path | None = None) -> Path:
    path = view_path(day, outputs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(view, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def load_view(day: str, outputs_dir: Path | None = None) -> dict:
    return json.loads(view_path(day, outputs_dir).read_text(encoding="utf-8"))


def save_html(html: str, day: str, outputs_dir: Path | None = None, artifact: bool = False) -> Path:
    path = artifact_path(day, outputs_dir) if artifact else html_path(day, outputs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
