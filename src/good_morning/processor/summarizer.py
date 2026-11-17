"""LLM による記事要約モジュール"""

import logging
import os
from pathlib import Path

import anthropic
import yaml

from good_morning.models import Article
from good_morning.paths import CONFIG_DIR

logger = logging.getLogger(__name__)

# config/prompts.yaml に model の指定がないときの既定値（aion と同じ）
DEFAULT_MODEL = "claude-sonnet-5"


def load_prompts(config_path: Path | None = None) -> dict:
    """プロンプト設定をYAMLから読み込む"""
    if config_path is None:
        config_path = CONFIG_DIR / "prompts.yaml"

    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def summarize_article(article: Article, client: anthropic.Anthropic, prompts: dict) -> Article:
    """単一記事の要約を生成"""
    prompt_config = prompts["summarize_article"]

    # 記事内容（summaryがあればそれを使用、なければタイトルのみ）
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
        max_tokens=1024,
        system=prompt_config["system"],
        messages=[{"role": "user", "content": user_prompt}],
    )

    result_text = response.content[0].text

    # レスポンスをパースして要約とWhy it mattersを抽出
    ai_summary, why_it_matters = parse_summary_response(result_text)

    # 記事オブジェクトを更新
    article.ai_summary = ai_summary
    article.why_it_matters = why_it_matters

    return article


def parse_summary_response(text: str) -> tuple[str, str]:
    """LLMレスポンスから要約とWhy it mattersを抽出"""
    ai_summary = ""
    why_it_matters = ""

    lines = text.split("\n")
    current_section = None

    for line in lines:
        if "### 要約" in line or "## 要約" in line:
            current_section = "summary"
        elif "### Why it matters" in line or "## Why it matters" in line:
            current_section = "why"
        elif current_section == "summary":
            ai_summary += line + "\n"
        elif current_section == "why":
            why_it_matters += line + "\n"

    return ai_summary.strip(), why_it_matters.strip()


def summarize_articles(articles: list[Article]) -> list[Article]:
    """複数記事の要約を生成

    どの記事を何件要約するかは選定側（good_morning.selector.ranking.select_for_summary）の
    責務なので、ここでは渡された記事をそのまま要約する。
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=api_key)
    prompts = load_prompts()

    logger.info("要約対象: %d 件", len(articles))

    summarized = []
    for i, article in enumerate(articles, 1):
        logger.info("  [%d/%d] %s...", i, len(articles), article.title[:40])
        try:
            summarized_article = summarize_article(article, client, prompts)
            summarized.append(summarized_article)
        except Exception:
            logger.exception("    要約に失敗: %s", article.title[:40])
            summarized.append(article)  # エラー時は元の記事をそのまま追加

    logger.info("要約完了: %d 件", len(summarized))
    return summarized
