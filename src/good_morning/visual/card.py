"""Discord に載せる画像のカード（ビューモデルから HTML を作り、ブラウザで画像にする）

画像にするのは Playwright（Chromium のヘッドレス版）。入っていない・起動できないときは
画像なしで続ける（通知は文字だけで送る。大原則3）。カードの HTML は外部の読み込みがなく、
ネットワークには触れない。
"""

import logging
from pathlib import Path

from good_morning.paths import OUTPUTS_DIR
from good_morning.visual.render import _environment, upgrade_view

logger = logging.getLogger(__name__)

CARD_WIDTH = 420  # CSS の幅（スマホの幅で読む前提）
CARD_SCALE = 3  # 画像の解像度の倍率（文字をくっきりさせる）


def card_path(day: str, outputs_dir: Path | None = None) -> Path:
    return (outputs_dir or OUTPUTS_DIR) / f"{day}-card.png"


def render_card_html(view: dict) -> str:
    return _environment().get_template("card.html.j2").render(v=upgrade_view(view))


def render_card_png(view: dict, out_path: Path) -> Path | None:
    """カードを PNG にして保存する。できなければ None（理由はログ）"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("画像のカード: Playwright が入っていないため作りません（pip install playwright）")
        return None

    html = render_card_html(view)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    viewport={"width": CARD_WIDTH, "height": 900}, device_scale_factor=CARD_SCALE
                )
                page.set_content(html, wait_until="load")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                page.locator(".card").screenshot(path=str(out_path))
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001 - 画像が作れなくても通知は文字だけで送る
        logger.warning(
            "画像のカード: 作れませんでした（%s: %s）。`python -m playwright install chromium` が必要かもしれません",
            type(e).__name__,
            str(e).splitlines()[0][:200] if str(e) else "",
        )
        return None
    return out_path
