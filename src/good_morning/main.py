"""good-morning CLI - 暗号資産投資向けモーニングレター"""

import logging
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from good_morning.logging_setup import setup_logging
from good_morning.paths import OUTPUTS_DIR, PROJECT_ROOT
from good_morning.reporter import ReportMeta, render_report, save_report
from good_morning.reporter.markdown import format_report_date
from good_morning.sections import RunContext, build_sections
from good_morning.selector import collect, explain_selection, keyword_filter_exempt_sources
from good_morning.timeutil import now_jst
from good_morning.watchlist import load_watchlist

logger = logging.getLogger(__name__)

app = typer.Typer(help="good-morning - 暗号資産投資向けモーニングレター生成ツール")


def _init() -> None:
    """全コマンド共通の初期化（.env の読み込みとログ設定）"""
    load_dotenv(PROJECT_ROOT / ".env")
    log_path = setup_logging()
    logger.debug("ログ出力先: %s", log_path)


@app.command()
def run(
    publish: Annotated[
        bool, typer.Option("--publish", "-p", help="Notion にも書き出す（任意）")
    ] = False,
    output_dir: Annotated[
        Path | None, typer.Option("--output-dir", help="出力先（省略時は outputs/）")
    ] = None,
    notify: Annotated[
        bool, typer.Option("--notify", help="Discord に通知する（同じ日は1回だけ）")
    ] = False,
    force_notify: Annotated[
        bool, typer.Option("--force-notify", help="その日送信済みでも Discord に送り直す")
    ] = False,
    notify_preview: Annotated[
        bool, typer.Option("--notify-preview", help="通知の文面を表示するだけで送らない")
    ] = False,
):
    """モーニングレターを生成して outputs/YYYY-MM-DD.md に保存する"""
    _init()
    now = now_jst()
    logger.info("モーニングレター生成: %s", format_report_date(now))

    meta = ReportMeta(generated_at=now)

    try:
        watchlist = load_watchlist()
    except Exception:
        logger.exception("ウォッチリストの読み込みに失敗しました")
        watchlist = None
        meta.notices.append("ウォッチリストの読み込みに失敗しました（理由はログを参照）")
    else:
        if watchlist.is_example:
            meta.notices.append(
                "config/watchlist.yaml がないため、見本（watchlist.example.yaml）の銘柄で作成しています"
            )

    logger.info("セクション作成:")
    ctx = RunContext(now=now, watchlist=watchlist)
    sections = build_sections(ctx)

    report = render_report(sections, meta)
    filepath = save_report(report, now, output_dir)
    logger.info("保存: %s", filepath)

    # ビジュアルレポート（JSON から HTML を描く）と画像のカード。失敗しても Markdown は保存済みなので止めない
    day = now.strftime("%Y-%m-%d")
    view, card = None, None
    try:
        from good_morning.visual.card import card_path, render_card_png
        from good_morning.visual.render import render_html, save_html, save_view
        from good_morning.visual.viewmodel import build_view

        view = build_view(ctx, sections, meta)
        save_view(view, day, output_dir)
        html_file = save_html(render_html(view), day, output_dir)
        save_html(render_html(view, standalone=False), day, output_dir, artifact=True)
        logger.info("ビジュアルレポート: %s（アーティファクト用も保存）", html_file)
        card = render_card_png(view, card_path(day, output_dir))
        if card:
            logger.info("画像のカード: %s", card)
    except Exception:
        logger.exception("ビジュアルレポートの作成に失敗しました")

    link = None
    if publish:
        # Notion 連携は任意機能。失敗してもローカル保存は済んでいるので止めない
        from good_morning.publisher import publish_to_notion_sync
        from good_morning.publisher.notion_mcp import extract_page_url

        try:
            result = publish_to_notion_sync(report)
            link = extract_page_url(result)
            logger.info("Notion: 書き出し完了（ページ: %s）", link or "URL を取得できませんでした")
        except Exception:
            logger.exception("Notion への書き出しに失敗しました")

    if (notify or force_notify or notify_preview) and view is not None:
        # 通知も任意機能。失敗しても例外にせず、理由をログに残す（レポートの保存は済んでいる）
        # リンクは Notion に書き出せたらそのページ、なければ REPORT_URL（アーティファクト）、なければ保存先
        _send_notification(
            view, card, link or _report_url(), str(filepath), now.date(),
            force=force_notify, preview=notify_preview,
        )


REPORT_URL_ENV = "REPORT_URL"


def _report_url() -> str | None:
    """詳しいレポートを置いた場所（claude.ai のアーティファクトなど）。.env の REPORT_URL"""
    import os

    url = os.environ.get(REPORT_URL_ENV, "").strip()
    return url or None


def _send_notification(view, card, link, report_path, day, *, force=False, preview=False) -> None:
    from good_morning.notify.discord import load_notify_config, notify_once
    from good_morning.notify.message import build_notification

    if not load_notify_config().discord.attach_card:
        card = None  # notify.yaml で画像の添付をやめている

    message = build_notification(view, link, report_path, with_image=card is not None)
    if preview:
        typer.echo("--- 通知の文面（送信しません）---")
        typer.echo(message)
        typer.echo(f"（画像: {card or 'なし'}）")
        return
    result = notify_once(message, day, force=force, image=card)
    log = logger.info if result.sent else logger.warning
    log("Discord: %s", result.reason)


@app.command()
def notify(
    day: Annotated[
        str | None, typer.Argument(help="日付（YYYY-MM-DD。省略時は最新）")
    ] = None,
    link: Annotated[
        str | None,
        typer.Option("--link", help="通知に載せるリンク（省略時は .env の REPORT_URL）"),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="その日送信済みでも送り直す")] = False,
    preview: Annotated[bool, typer.Option("--preview", help="文面を表示するだけで送らない")] = False,
):
    """保存済みのレポートの通知を Discord に送る（画像のカードがあれば添付する）

    毎朝のタスクで、アーティファクトにレポートを公開したあとに呼ぶ想定。
    """
    from datetime import date as date_type

    _init()
    from good_morning.visual.card import card_path
    from good_morning.visual.render import load_view

    if day is None:
        views = sorted(OUTPUTS_DIR.glob("????-??-??.json"), reverse=True)
        if not views:
            typer.echo("保存済みのデータがありません。先に run コマンドを実行してください。")
            raise typer.Exit(1)
        day = views[0].stem
    card = card_path(day)
    _send_notification(
        load_view(day),
        card if card.exists() else None,
        link or _report_url(),
        str(OUTPUTS_DIR / f"{day}.html"),
        date_type.fromisoformat(day),
        force=force,
        preview=preview,
    )


@app.command()
def render(
    day: Annotated[
        str | None, typer.Argument(help="日付（YYYY-MM-DD。省略時は最新）")
    ] = None,
):
    """保存済みのデータ（outputs/YYYY-MM-DD.json）からビジュアルレポートの HTML だけを作り直す"""
    _init()
    from good_morning.visual.render import load_view, render_html, save_html

    if day is None:
        views = sorted(OUTPUTS_DIR.glob("????-??-??.json"), reverse=True)
        if not views:
            typer.echo("保存済みのデータがありません。先に run コマンドを実行してください。")
            raise typer.Exit(1)
        day = views[0].stem
    view = load_view(day)
    path = save_html(render_html(view), day)
    artifact = save_html(render_html(view, standalone=False), day, artifact=True)
    typer.echo(f"ビジュアルレポート: {path}")
    typer.echo(f"アーティファクト用: {artifact}")


@app.command()
def collect_cmd(
    days: Annotated[int, typer.Option("--days", "-d", help="取得する日数")] = 1,
    explain: Annotated[
        bool, typer.Option("--explain", help="記事ごとに通過/除外の理由を表示")
    ] = False,
):
    """RSSフィードから記事を収集する（ニュース選定の確認用）"""
    _init()
    if explain:
        articles = explain_selection(days=days)
        exempt = keyword_filter_exempt_sources()
        for article in articles:
            status = "通過" if article.excluded_reason is None else f"除外: {article.excluded_reason}"
            if article.matched_keywords:
                keywords = ", ".join(article.matched_keywords)
            elif article.source in exempt:
                # キーワード0件でも通過した理由が読み取れるようにする
                keywords = "-（キーワードフィルタ免除）"
            else:
                keywords = "-"
            typer.echo(
                f"[{status}] score={article.score:5.1f} | {article.source} "
                f"| {article.title[:60]} | matched: {keywords}"
            )

        passed = sum(1 for a in articles if a.excluded_reason is None)
        typer.echo(f"\n合計 {len(articles)} 件 / 通過 {passed} 件")
        return

    articles = collect(days=days)
    typer.echo(f"\n取得完了: {len(articles)} 件")


@app.command()
def publish(
    filepath: Annotated[
        Path | None, typer.Argument(help="書き出すMarkdownファイル（省略時は最新レポート）")
    ] = None,
):
    """既存のレポートを Notion に書き出す（MCP経由・任意機能）"""
    _init()
    from good_morning.publisher import publish_to_notion_sync

    if filepath is None:
        reports = sorted(OUTPUTS_DIR.glob("????-??-??.md"), reverse=True)
        if not reports:
            typer.echo("レポートが見つかりません。先に run コマンドを実行してください。")
            raise typer.Exit(1)
        filepath = reports[0]

    typer.echo(f"ファイル読み込み: {filepath}")
    content = filepath.read_text(encoding="utf-8")

    typer.echo("Notionに書き出し中...")
    result = publish_to_notion_sync(content)
    typer.echo(f"完了: {result}")


if __name__ == "__main__":
    app()
