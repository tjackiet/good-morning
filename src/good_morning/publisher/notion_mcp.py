"""Notion MCP を使った書き出しモジュール（任意機能。aion から引き継ぎ）

書き出し先の親ページIDは環境変数 NOTION_PAGE_ID で渡す（公開リポジトリのため
コードに直書きしない）。Notion 側でそのページへの接続を許可しておくこと。
"""

import asyncio
import logging
import os
import re

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from good_morning.net import NODE_SYSTEM_CA_ENV
from good_morning.reporter.markdown import REPORT_TITLE, format_report_date
from good_morning.timeutil import now_jst

logger = logging.getLogger(__name__)

NOTION_PAGE_ID_ENV = "NOTION_PAGE_ID"
_NOTION_URL = re.compile(r"https://(?:www\.)?notion\.(?:so|site)/[^\s\"'<>)\]]+")


def extract_page_url(result_text: str | None) -> str | None:
    """Notion MCP の応答の文章から、作成したページの URL を取り出す（見つからなければ None）"""
    if not result_text:
        return None
    match = _NOTION_URL.search(result_text)
    return match.group().rstrip(".,") if match else None


def get_parent_page_id() -> str:
    page_id = os.environ.get(NOTION_PAGE_ID_ENV)
    if not page_id:
        raise ValueError(f"環境変数 {NOTION_PAGE_ID_ENV} が設定されていません（.env を確認）")
    return page_id


async def call_notion_mcp(tool_name: str, arguments: dict) -> dict:
    """Notion MCP サーバーのツールを呼び出す"""
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "mcp-remote", "https://mcp.notion.com/sse"],
        env=dict(NODE_SYSTEM_CA_ENV),
    )

    async with (
        stdio_client(server_params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool(tool_name, arguments)


def publish_to_notion_sync(report_content: str, title: str | None = None) -> str:
    """レポートを Notion に書き出す（同期版）"""
    return asyncio.run(publish_to_notion(report_content, title))


async def publish_to_notion(report_content: str, title: str | None = None) -> str:
    """レポートを Notion に書き出す"""
    parent_page_id = get_parent_page_id()
    if title is None:
        title = f"{REPORT_TITLE} {format_report_date(now_jst())}"

    logger.info("Notion に書き出し中: %s", title)

    # Notion MCP の notion-create-pages ツールを使用
    # pages は配列形式、parent で親ページを指定
    result = await call_notion_mcp(
        "notion-create-pages",
        {
            "parent": {"page_id": parent_page_id},
            "pages": [{"properties": {"title": title}, "content": report_content}],
        },
    )

    logger.info("Notion への書き出し完了")

    # 結果からURLを取得
    if hasattr(result, "content") and result.content:
        for content in result.content:
            if hasattr(content, "text"):
                return content.text

    return str(result)
