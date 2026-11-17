"""Claude による記事要約モジュール（「要約」と「暗号資産への示唆」）

大原則1: LLM に数値を作らせない。プロンプト（config/prompts.yaml）で、記事にない数値を
足さないよう指示している。要約に失敗した記事は要約なしのまま返し、全体は止めない（大原則3）。

Claude Sonnet 5 は既定で思考（thinking）が有効なので、応答の先頭が thinking ブロックの
ことがある。content[0] を決め打ちせず、type が "text" のブロックだけを取り出す。
"""

import logging
import os
from pathlib import Path

import anthropic
import yaml

from good_morning.models import Article
from good_morning.paths import CONFIG_DIR

logger = logging.getLogger(__name__)

# config/prompts.yaml に指定がないときの既定値（model は aion と同じ）
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 4000
CREDENTIAL_ENVS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

SECTION_SUMMARY = "要約"
SECTION_IMPLICATION = "暗号資産への示唆"


class SummarizerUnavailable(Exception):
    """要約そのものができない（認証情報がない など）"""


class SummaryError(Exception):
    """1記事の要約に失敗した"""


def load_prompts(config_path: Path | None = None) -> dict:
    """プロンプト設定をYAMLから読み込む"""
    if config_path is None:
        config_path = CONFIG_DIR / "prompts.yaml"

    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_client() -> anthropic.Anthropic:
    """Anthropic のクライアントを作る。認証情報が環境変数になければ使えないと判断する"""
    if not any(os.environ.get(name) for name in CREDENTIAL_ENVS):
        raise SummarizerUnavailable(
            "ANTHROPIC_API_KEY が設定されていないため、要約できません（.env を確認）"
        )
    return anthropic.Anthropic()


def response_text(response) -> str:
    """応答から text ブロックだけをつなげて返す（thinking ブロックは飛ばす）"""
    if getattr(response, "stop_reason", None) == "refusal":
        raise SummaryError("Claude が要約を断りました（stop_reason=refusal）")
    texts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    if not texts:
        raise SummaryError("応答に文章がありません")
    if getattr(response, "stop_reason", None) == "max_tokens":
        logger.warning("要約が max_tokens で切れました（prompts.yaml の max_tokens を増やしてください）")
    return "\n".join(texts)


def parse_summary_response(text: str) -> tuple[str, str]:
    """LLMレスポンスから「要約」と「暗号資産への示唆」を抽出"""
    sections: dict[str, list[str]] = {SECTION_SUMMARY: [], SECTION_IMPLICATION: []}
    current = None

    for line in text.split("\n"):
        heading = line.strip().lstrip("#").strip()
        if line.lstrip().startswith("#") and heading in sections:
            current = heading
        elif current is not None:
            sections[current].append(line)

    return (
        "\n".join(sections[SECTION_SUMMARY]).strip(),
        "\n".join(sections[SECTION_IMPLICATION]).strip(),
    )


def summarize_article(article: Article, client: anthropic.Anthropic, prompts: dict) -> Article:
    """単一記事の要約を生成"""
    prompt_config = prompts["summarize_article"]

    # 記事内容（RSS の概要があればそれを使用、なければタイトルのみ）
    content = article.summary or article.title

    user_prompt = prompt_config["user"].format(
        title=article.title,
        source=article.source,
        url=article.url,
        published=article.published.strftime("%Y-%m-%d") if article.published else "不明",
        content=content,
    )

    response = client.messages.create(
        model=prompts.get("model", DEFAULT_MODEL),
        max_tokens=int(prompts.get("max_tokens", DEFAULT_MAX_TOKENS)),
        system=prompt_config["system"],
        messages=[{"role": "user", "content": user_prompt}],
    )

    summary, implication = parse_summary_response(response_text(response))
    if not summary:
        raise SummaryError("応答に「要約」の見出しがありません")

    article.ai_summary = summary
    article.crypto_implication = implication or None
    return article


def summarize_articles(
    articles: list[Article], client: anthropic.Anthropic | None = None
) -> list[Article]:
    """複数記事の要約を生成する

    どの記事を何件要約するかは選定側（good_morning.selector.ranking.select_for_summary）の
    責務なので、ここでは渡された記事をそのまま要約する。
    認証情報がなければ SummarizerUnavailable を投げる。1記事の失敗は要約なしのまま続ける。
    """
    client = client or make_client()
    prompts = load_prompts()

    logger.info("要約対象: %d 件", len(articles))
    for i, article in enumerate(articles, 1):
        logger.info("  [%d/%d] %s...", i, len(articles), article.title[:40])
        try:
            summarize_article(article, client, prompts)
        except anthropic.AuthenticationError as e:
            # キーが無効なら、残りの記事も同じ理由で失敗するので打ち切る
            raise SummarizerUnavailable(
                f"Anthropic の認証に失敗しました（{type(e).__name__}）"
            ) from e
        except (anthropic.APIStatusError, anthropic.APIConnectionError, SummaryError) as e:
            # SDK は 429・5xx・接続エラーを自動で2回まで再試行している。それでも失敗したら要約なしで続ける
            logger.warning("    要約に失敗: %s: %s", type(e).__name__, e)

    done = sum(1 for a in articles if a.ai_summary)
    logger.info("要約完了: %d / %d 件", done, len(articles))
    return articles
