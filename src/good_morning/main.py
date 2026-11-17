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
    sections = build_sections(RunContext(now=now, watchlist=watchlist))

    report = render_report(sections, meta)
    filepath = save_report(report, now, output_dir)
    logger.info("保存: %s", filepath)

    if publish:
        # Notion 連携は任意機能。失敗してもローカル保存は済んでいるので止めない
        from good_morning.publisher import publish_to_notion_sync

        try:
            result = publish_to_notion_sync(report)
            logger.info("Notion: %s", result)
        except Exception:
            logger.exception("Notion への書き出しに失敗しました")


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
