"""bitbank-lab-mcp からの取得（MCP Python SDK、stdio。MCP に触れるのはこのファイルだけ）

使うのは各ツールの structuredContent（プログラム向けの JSON）だけで、文章の content は使わない。
文章のラベルは揺れがあるため（同じ RSI 37.0 が「中立圏」とも「弱め」とも書かれる）、
判定は数値から自前で行う（good_morning.crypto.technicals）。

公開データだけを使うので API キーは渡さない。MCP SDK は既定で一部の環境変数
（HOME・PATH など）しか子プロセスに渡さないため、親の環境にキーがあっても漏れない。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from good_morning.net import NODE_SYSTEM_CA_ENV

logger = logging.getLogger(__name__)

SERVER_PACKAGE = "bitbank-lab-mcp@0.8.0"
# npx の初回はパッケージの取得に時間がかかるので長めにとる
SESSION_TIMEOUT_SECONDS = 120

TIMEFRAMES = ("1day", "1week", "1month")
# 指標の計算に使う本数。bitbank-lab-mcp は内部でさらに過去の足を足して計算する
INDICATOR_LIMIT = 300


class BitbankMCPError(Exception):
    """bitbank-lab-mcp からの取得に失敗した"""


def server_parameters() -> StdioServerParameters:
    return StdioServerParameters(
        command="npx", args=["-y", SERVER_PACKAGE], env=dict(NODE_SYSTEM_CA_ENV)
    )


@dataclass
class ToolCall:
    key: str
    tool: str
    arguments: dict[str, Any]


@dataclass
class BitbankSnapshot:
    """1回の実行で取得した bitbank のデータ（ツールごとに成功・失敗が分かれる）"""

    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> dict[str, Any]:
        if key in self.results:
            return self.results[key]
        raise BitbankMCPError(self.errors.get(key, f"{key}: 取得していません"))


def snapshot_calls(main_pair: str = "btc_jpy") -> list[ToolCall]:
    calls = [
        ToolCall(
            f"indicators_{tf}",
            "analyze_indicators",
            {"pair": main_pair, "type": tf, "limit": INDICATOR_LIMIT},
        )
        for tf in TIMEFRAMES
    ]
    calls.append(ToolCall("tickers_jpy", "get_tickers_jpy", {}))
    return calls


def structured_from_result(key: str, result) -> dict[str, Any]:
    """CallToolResult から structuredContent を取り出して検査する"""
    if getattr(result, "is_error", False):
        text = " ".join(getattr(c, "text", "") for c in getattr(result, "content", []) or [])
        raise BitbankMCPError(f"{key}: ツールがエラーを返しました（{text[:200]}）")

    structured = getattr(result, "structured_content", None)
    if not isinstance(structured, dict):
        raise BitbankMCPError(f"{key}: structuredContent がありません")
    if structured.get("ok") is False:
        raise BitbankMCPError(f"{key}: ok=false（{str(structured.get('summary'))[:200]}）")
    return structured


async def _fetch(calls: list[ToolCall]) -> BitbankSnapshot:
    snapshot = BitbankSnapshot()
    async with (
        stdio_client(server_parameters()) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        for call in calls:
            try:
                result = await session.call_tool(call.tool, call.arguments)
                snapshot.results[call.key] = structured_from_result(call.key, result)
            except Exception as e:  # noqa: BLE001 - 1つのツールの失敗で残りを止めない
                logger.warning("bitbank-lab-mcp %s: 取得失敗 - %s", call.key, e)
                snapshot.errors[call.key] = f"{call.key}: {type(e).__name__}: {e}"
    return snapshot


def fetch_snapshot(calls: list[ToolCall] | None = None) -> BitbankSnapshot:
    """MCP サーバーを1回起動し、必要なツールをまとめて呼ぶ"""
    calls = calls or snapshot_calls()
    try:
        return asyncio.run(asyncio.wait_for(_fetch(calls), timeout=SESSION_TIMEOUT_SECONDS))
    except Exception as e:
        raise BitbankMCPError(
            f"bitbank-lab-mcp に接続できませんでした（{type(e).__name__}: {e}）"
        ) from e
