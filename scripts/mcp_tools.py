"""MCP サーバーのツール一覧・入力スキーマを表示する（開発用）

aion の list_mcp_tools.py / get_tool_schema.py を1本にまとめ、
bitbank-lab-mcp も見られるようにしたもの。

使い方:
    python scripts/mcp_tools.py bitbank                        # ツール一覧
    python scripts/mcp_tools.py bitbank analyze_indicators     # 入力スキーマ
    python scripts/mcp_tools.py notion notion-create-pages
"""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVERS = {
    # 公開データのみ使うので API キーは渡さない
    "bitbank": StdioServerParameters(command="npx", args=["-y", "bitbank-lab-mcp@0.8.0"]),
    "notion": StdioServerParameters(
        command="npx", args=["-y", "mcp-remote", "https://mcp.notion.com/sse"]
    ),
}


async def show(server: str, tool_name: str | None) -> None:
    async with (
        stdio_client(SERVERS[server]) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        for tool in tools.tools:
            if tool_name is None:
                print(f"- {tool.name}")
            elif tool.name == tool_name:
                print(f"Tool: {tool.name}")
                print(f"Description: {tool.description}")
                print("Input Schema:")
                print(json.dumps(tool.inputSchema, ensure_ascii=False, indent=2))


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in SERVERS:
        print(__doc__)
        sys.exit(1)
    asyncio.run(show(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))


if __name__ == "__main__":
    main()
