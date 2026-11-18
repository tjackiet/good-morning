"""Discord 通知のテスト（Discord には接続しない）"""

from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from conftest import YF_PRE_OPEN_CAPTURED_AT

from good_morning.context import RunContext
from good_morning.notify import discord
from good_morning.notify.discord import (
    DiscordConfig,
    build_payload,
    load_notify_config,
    notify_once,
    send_discord,
)
from good_morning.notify.message import build_notification
from good_morning.publisher.notion_mcp import extract_page_url
from good_morning.reporter.markdown import STATUS_FAILED, STATUS_OK, Section
from good_morning.synthesis.claude import Synthesis

WEBHOOK = "https://discord.com/api/webhooks/123/secret-token"


class FakePost:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, params=None, json=None, headers=None, timeout=None, verify=None):
        self.calls.append(
            {"url": url, "params": params, "json": json, "headers": headers, "timeout": timeout, "verify": verify}
        )
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _resp(status, body=None):
    return SimpleNamespace(status_code=status, json=lambda: body or {})


@pytest.fixture
def fake_post(monkeypatch):
    def _install(*responses):
        fake = FakePost(*responses)
        monkeypatch.setattr(discord.httpx, "post", fake)
        return fake

    return _install


def test_shipped_notify_config():
    config = load_notify_config().discord
    assert (config.suppress_embeds, config.silent, config.retry_on_429) == (True, False, True)


def test_payload_suppresses_mentions_and_sets_flags():
    payload = build_payload("@everyone テスト", DiscordConfig(suppress_embeds=True, silent=True))

    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["flags"] == 4 | 4096
    assert "flags" not in build_payload("x", DiscordConfig(suppress_embeds=False, silent=False))
    assert len(build_payload("あ" * 3000, DiscordConfig())["content"]) == discord.MAX_CONTENT_CHARS


def test_send_success_uses_user_agent_and_wait(fake_post):
    fake = fake_post(_resp(200))

    result = send_discord("hello", DiscordConfig(), webhook_url=WEBHOOK)

    assert result.sent
    call = fake.calls[0]
    assert call["headers"]["User-Agent"].startswith("good-morning/")
    assert call["params"] == {"wait": "true"}
    assert call["timeout"] == 10


def test_429_waits_retry_after_and_retries_once(fake_post):
    fake = fake_post(_resp(429, {"retry_after": 2.5}), _resp(200))
    waits = []

    result = send_discord("hello", DiscordConfig(), webhook_url=WEBHOOK, sleep=waits.append)

    assert result.sent and len(fake.calls) == 2
    assert waits == [2.5]


def test_429_twice_gives_up_and_caps_wait(fake_post):
    fake_post(_resp(429, {"retry_after": 120}), _resp(429, {"retry_after": 1}))
    waits = []

    result = send_discord("hello", DiscordConfig(), webhook_url=WEBHOOK, sleep=waits.append)

    assert not result.sent
    assert result.reason == "Discord が HTTP 429 を返しました"
    assert waits == [30]  # 上限


def test_errors_never_include_the_webhook_url(fake_post):
    try:
        raise OSError("certificate verify failed")
    except OSError as cause:
        error = httpx.ConnectError(f"failed to connect {WEBHOOK}")
        error.__cause__ = cause
    fake_post(error)

    result = send_discord("hello", DiscordConfig(), webhook_url=WEBHOOK)

    assert not result.sent
    assert "secret-token" not in result.reason and "discord.com" not in result.reason
    assert "ConnectError ← OSError" in result.reason


def test_http_error_reports_status_only(fake_post):
    fake_post(_resp(403))

    result = send_discord("hello", DiscordConfig(), webhook_url=WEBHOOK)

    assert result.reason == "Discord が HTTP 403 を返しました"


def test_missing_webhook_url_does_not_send(monkeypatch, fake_post):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    fake = fake_post()

    result = send_discord("hello", DiscordConfig())

    assert not result.sent and "DISCORD_WEBHOOK_URL" in result.reason
    assert fake.calls == []


def test_notify_once_records_and_skips_second_send(tmp_path, fake_post):
    fake = fake_post(_resp(200), _resp(200))
    day = date(2026, 11, 18)
    kwargs = {"config": DiscordConfig(), "webhook_url": WEBHOOK, "outputs_dir": tmp_path}

    first = notify_once("hello", day, **kwargs)
    second = notify_once("hello", day, **kwargs)
    forced = notify_once("hello", day, force=True, **kwargs)

    assert first.sent and not second.sent and forced.sent
    assert "送信済み" in second.reason
    assert len(fake.calls) == 2


def test_failed_send_is_not_recorded(tmp_path, fake_post):
    fake_post(_resp(500))

    notify_once("hello", date(2026, 11, 18), config=DiscordConfig(), webhook_url=WEBHOOK, outputs_dir=tmp_path)

    assert not discord.sent_marker(date(2026, 11, 18), tmp_path).exists()


def test_notification_message():
    synthesis = Synthesis(
        stance="リスクオフ",
        summary_lines=["一行目。", "二行目。", "三行目。"],
        btc_comment="c",
        bullish=["b"],
        bearish=["d"],
        conclusion="e",
    )
    ctx = RunContext(now=YF_PRE_OPEN_CAPTURED_AT, data={"synthesis": synthesis})
    sections = [
        Section(key="markets", title="マーケット一覧", status=STATUS_OK),
        Section(key="news", title="主要ニュース", status=STATUS_FAILED),
    ]

    with_link = build_notification(ctx, sections, "https://www.notion.so/abc", "outputs/2026-11-17.md")
    without_link = build_notification(ctx, sections, None, "outputs/2026-11-17.md")

    assert with_link.splitlines()[0] == "**🌅 モーニングレター 11/17（火）**"
    assert "判定: 🔴 **リスクオフ**" in with_link
    assert "1. 一行目。" in with_link
    assert "⚠ 取得失敗: 主要ニュース" in with_link
    assert with_link.endswith("[レポートを開く](https://www.notion.so/abc)")
    assert without_link.endswith("レポート: outputs/2026-11-17.md（このMacに保存）")


def test_notification_without_synthesis():
    message = build_notification(RunContext(now=YF_PRE_OPEN_CAPTURED_AT), [], None, "x.md")

    assert "（今朝のまとめは作成できませんでした）" in message


@pytest.mark.parametrize(
    "text,url",
    [
        ('{"pages":[{"url":"https://www.notion.so/2de5abc123"}]}', "https://www.notion.so/2de5abc123"),
        ("Created page: https://www.notion.so/My-Page-0123abcd.", "https://www.notion.so/My-Page-0123abcd"),
        ("no url here", None),
        (None, None),
    ],
)
def test_extract_page_url(text, url):
    assert extract_page_url(text) == url
