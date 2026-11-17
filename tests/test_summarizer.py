"""good_morning.processor.summarizer のテスト（Claude API には接続しない）"""

from types import SimpleNamespace

import anthropic
import httpx
import pytest

from good_morning.processor import summarizer
from good_morning.processor.summarizer import (
    SummarizerUnavailable,
    SummaryError,
    load_prompts,
    parse_summary_response,
    response_text,
    summarize_article,
    summarize_articles,
)

REPLY = """### 要約
米連銀の利上げ観測が強まり、ビットコインは下落した。

### 暗号資産への示唆
金利上昇は暗号資産の重しになりうる。"""


def _response(text=REPLY, stop_reason="end_turn", thinking=True):
    blocks = []
    if thinking:
        # Claude Sonnet 5 は既定で thinking が有効。先頭に thinking ブロックが来る
        blocks.append(SimpleNamespace(type="thinking", thinking=""))
    blocks.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _api_error(cls, status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("error", response=httpx.Response(status, request=request), body=None)


def test_prompt_config_follows_spec():
    prompts = load_prompts()

    assert prompts["model"] == "claude-sonnet-5"  # aion と同じ（指示書の指定）
    assert "暗号資産への示唆" in prompts["summarize_article"]["user"]
    assert "新しい数値を作ったり" in prompts["summarize_article"]["system"]  # 大原則1


def test_parse_summary_response():
    summary, implication = parse_summary_response(REPLY)

    assert summary == "米連銀の利上げ観測が強まり、ビットコインは下落した。"
    assert implication == "金利上昇は暗号資産の重しになりうる。"


def test_response_text_skips_thinking_blocks():
    assert response_text(_response()) == REPLY


def test_response_text_rejects_refusal():
    with pytest.raises(SummaryError, match="refusal"):
        response_text(_response(stop_reason="refusal"))


def test_summarize_article_fills_fields(make_article):
    article = make_article(title="Bitcoin falls", summary="<p>概要</p>")
    client = FakeClient([_response()])

    summarize_article(article, client, load_prompts())

    assert article.ai_summary.startswith("米連銀の利上げ観測")
    assert article.crypto_implication == "金利上昇は暗号資産の重しになりうる。"
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5"
    assert call["max_tokens"] == 4000


def test_summarize_articles_continues_after_one_failure(make_article):
    """1記事の失敗（429 が再試行後も続いた など）は要約なしで続ける"""
    first, second = make_article(title="a"), make_article(title="b")
    client = FakeClient([_api_error(anthropic.RateLimitError, 429), _response()])

    summarize_articles([first, second], client=client)

    assert first.ai_summary is None
    assert second.ai_summary is not None


def test_authentication_error_stops_remaining(make_article):
    articles = [make_article(title="a"), make_article(title="b")]
    client = FakeClient([_api_error(anthropic.AuthenticationError, 401), _response()])

    with pytest.raises(SummarizerUnavailable, match="認証"):
        summarize_articles(articles, client=client)
    assert len(client.calls) == 1


def test_missing_credentials(monkeypatch):
    for name in summarizer.CREDENTIAL_ENVS:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SummarizerUnavailable, match="ANTHROPIC_API_KEY"):
        summarizer.make_client()
