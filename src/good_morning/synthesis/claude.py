"""Claude で「今朝のまとめ」「BTC のまとめ」「暗号資産への示唆」を1回の呼び出しで作る

- 渡すのは build_facts() が作った計算済みの数値だけ（大原則1）。
- 出力は output_config.format（json_schema）で形を固定し、pydantic でも検査する。
- 出力に出てきた数値を、渡したデータの数値と機械的に照合する。データにない数値があれば、
  その数値を伝えて1回だけ作り直させる。それでも残れば、レポートに「確認できなかった数値」として出す。
- 結果（失敗も）は ctx.data に覚えておき、2つのセクションから呼んでも Claude は1回だけ呼ぶ。
"""

import json
import logging
from typing import Literal

from pydantic import BaseModel, ValidationError

from good_morning.context import RunContext
from good_morning.processor import summarizer
from good_morning.synthesis.facts import build_facts
from good_morning.synthesis.numbers import unknown_numbers
from good_morning.synthesis.stale import annotate_stale_dates, stale_values

logger = logging.getLogger(__name__)

STANCES = ("リスクオン", "リスクオフ", "様子見")
_CACHE_KEY = "_synthesis"
DEFAULT_MAX_TOKENS = 8000

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "stance": {"type": "string", "enum": list(STANCES)},
        "summary_lines": {"type": "array", "items": {"type": "string"}},
        "btc_comment": {"type": "string"},
        "bullish": {"type": "array", "items": {"type": "string"}},
        "bearish": {"type": "array", "items": {"type": "string"}},
        "conclusion": {"type": "string"},
    },
    "required": ["stance", "summary_lines", "btc_comment", "bullish", "bearish", "conclusion"],
    "additionalProperties": False,
}


class SynthesisError(Exception):
    """まとめを作れなかった"""


class Synthesis(BaseModel):
    stance: Literal["リスクオン", "リスクオフ", "様子見"]
    summary_lines: list[str]
    btc_comment: str
    bullish: list[str]
    bearish: list[str]
    conclusion: str
    # 照合でデータに見つからなかった数値（作り直したあとも残ったもの）
    unverified_numbers: list[str] = []

    def all_text(self) -> str:
        parts = [*self.summary_lines, self.btc_comment, *self.bullish, *self.bearish, self.conclusion]
        return "\n".join(parts)

    def payload(self) -> dict:
        return self.model_dump(exclude={"unverified_numbers"})


def request_synthesis(client, prompts: dict, facts: str, retry: tuple[dict, list[str]] | None = None):
    """Claude を1回呼んで Synthesis を返す。retry=(前回の出力, データにない数値) なら作り直させる"""
    config = prompts["synthesis"]
    messages = [{"role": "user", "content": config["user"].format(facts=facts)}]
    if retry is not None:
        previous, unknown = retry
        messages.append({"role": "assistant", "content": json.dumps(previous, ensure_ascii=False)})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"次の数値は渡したデータにありません: {', '.join(unknown)}。"
                    "計算・換算・推測をせず、データに書かれた数値だけを、表記を変えずに使って作り直してください。"
                ),
            }
        )

    response = client.messages.create(
        model=prompts.get("model", summarizer.DEFAULT_MODEL),
        max_tokens=int(config.get("max_tokens", DEFAULT_MAX_TOKENS)),
        system=config["system"],
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    text = summarizer.response_text(response)
    try:
        return Synthesis(**json.loads(text))
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        raise SynthesisError(f"Claude の出力が想定の形ではありません（{type(e).__name__}）") from e


def synthesize(ctx: RunContext, client=None, prompts: dict | None = None) -> Synthesis:
    facts = build_facts(ctx)
    if facts.count("\n## ") == 0:
        raise SynthesisError("まとめの材料になるデータがありません（すべてのセクションが取得失敗）")

    client = client or summarizer.make_client()
    prompts = prompts or summarizer.load_prompts()

    result = request_synthesis(client, prompts, facts)
    unknown = unknown_numbers(result.all_text(), facts)
    if unknown:
        logger.warning("まとめにデータにない数値があったため作り直します: %s", ", ".join(unknown))
        result = request_synthesis(client, prompts, facts, retry=(result.payload(), unknown))
        result.unverified_numbers = unknown_numbers(result.all_text(), facts)
        if result.unverified_numbers:
            logger.warning(
                "作り直してもデータにない数値が残りました: %s", ", ".join(result.unverified_numbers)
            )

    if len(result.summary_lines) != 3:
        logger.warning("まとめの行数が3ではありません（%d行）", len(result.summary_lines))
        result.summary_lines = result.summary_lines[:3]
    add_stale_dates(result, ctx)
    return result


def add_stale_dates(result: Synthesis, ctx: RunContext) -> None:
    """前の営業日の終値を日付なしで使った文に、日付を添える（BTC のまとめはテクニカルの話なので見ない）"""
    values = stale_values(ctx)
    if not values:
        return
    before = result.all_text()
    result.summary_lines = [annotate_stale_dates(line, values) for line in result.summary_lines]
    result.bullish = [annotate_stale_dates(item, values) for item in result.bullish]
    result.bearish = [annotate_stale_dates(item, values) for item in result.bearish]
    result.conclusion = annotate_stale_dates(result.conclusion, values)
    if result.all_text() != before:
        logger.info("まとめ: 前の営業日の終値を使った文に日付を添えました")


def get_synthesis(ctx: RunContext) -> Synthesis:
    """1回の実行で1度だけ Claude を呼ぶ（失敗も覚えておき、呼び直さない）"""
    cached = ctx.data.get(_CACHE_KEY)
    if cached is None:
        try:
            cached = synthesize(ctx)
        except Exception as e:  # noqa: BLE001 - 失敗を覚えて、各セクションで「取得失敗」にする
            logger.error("まとめ（Claude）: %s: %s", type(e).__name__, e)
            cached = e
        ctx.data[_CACHE_KEY] = cached
    if isinstance(cached, Exception):
        raise cached
    ctx.data["synthesis"] = cached
    return cached
