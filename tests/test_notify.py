"""Discord 通知のテスト（Discord には接続しない）"""

import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

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

WEBHOOK = "https://discord.com/api/webhooks/123/secret-token"


class FakePost:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(
        self, url, params=None, json=None, headers=None, timeout=None, verify=None, data=None, files=None
    ):
        self.calls.append(
            {"url": url, "params": params, "json": json, "headers": headers, "timeout": timeout,
             "verify": verify, "data": data, "files": files}
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


VIEW = {
    "date_label": "2026年11月17日（火）",
    "summary": {"stance": "リスクオフ", "lines": ["一行目。", "二行目。", "三行目。"], "unverified": []},
    "markets": {"hero": {"name": "BTC/JPY", "value": "10,344,652", "pct_label": "+1.28%", "failed": False}},
    "btc": {"timeframes": [{"label": "日足", "verdict": "弱気", "total": -4}]},
    "failed_sections": ["主要ニュース"],
}


def test_notification_message_without_image():
    with_link = build_notification(VIEW, "https://app.notion.com/p/abc", "outputs/2026-11-17.html")
    without_link = build_notification(VIEW, None, "outputs/2026-11-17.html")

    assert with_link.splitlines()[0] == "**🌅 モーニングレター 2026年11月17日（火）**"
    assert "判定: 🔴 **リスクオフ**" in with_link
    assert "1. 一行目。" in with_link
    assert "BTC/JPY 10,344,652円（24時間 +1.28%）・日足 弱気（-4）" in with_link
    assert "⚠ 取得失敗: 主要ニュース" in with_link
    assert with_link.endswith("[レポートを開く](https://app.notion.com/p/abc)")
    assert without_link.endswith("レポート: outputs/2026-11-17.html（このMacに保存）")


def test_notification_with_image_is_short():
    """画像のカードに同じ内容が載るので、文章は判定・取得失敗・リンクだけにする"""
    message = build_notification(VIEW, "https://claude.ai/artifact/x", "x.html", with_image=True)

    assert "判定: 🔴 **リスクオフ**" in message
    assert "1. 一行目。" not in message and "BTC/JPY" not in message
    assert "⚠ 取得失敗: 主要ニュース" in message
    assert message.endswith("[レポートを開く](https://claude.ai/artifact/x)")


def test_notification_without_summary():
    assert "（今朝のまとめは作成できませんでした）" in build_notification({}, None, "x.html")


def test_image_is_sent_as_multipart(fake_post, tmp_path):
    fake = fake_post(_resp(200))
    image = tmp_path / "2026-11-18-card.png"
    image.write_bytes(b"\x89PNG fake")

    result = send_discord("hello", DiscordConfig(), webhook_url=WEBHOOK, image=image)

    assert result.sent
    call = fake.calls[0]
    assert call["json"] is None
    assert json.loads(call["data"]["payload_json"])["allowed_mentions"] == {"parse": []}
    name, content, mime = call["files"]["files[0]"]
    assert (name, content, mime) == ("2026-11-18-card.png", b"\x89PNG fake", "image/png")


def test_unreadable_image_falls_back_to_text(fake_post, tmp_path):
    fake = fake_post(_resp(200))

    result = send_discord("hello", DiscordConfig(), webhook_url=WEBHOOK, image=tmp_path / "missing.png")

    assert result.sent
    assert fake.calls[0]["json"]["content"] == "hello"


@pytest.mark.parametrize(
    "text,url",
    [
        # 2026-11-18 に実際に返ってきた応答（id は伏せた）
        (
            (
                '{"pages":[{"id":"x","url":"https://app.notion.com/p/0123abcd?pvs=204",'
                '"properties":{"title":"モーニングレター 2026年11月18日（水）"}}]}'
            ),
            "https://app.notion.com/p/0123abcd?pvs=204",
        ),
        ('{"pages":[{"url":"https://www.notion.so/2de5abc123"}]}', "https://www.notion.so/2de5abc123"),
        ("Created: https://app.notion.com/p/0123abcd", "https://app.notion.com/p/0123abcd"),
        ('{"pages": []}', None),
        ("Created page: https://www.notion.so/My-Page-0123abcd.", "https://www.notion.so/My-Page-0123abcd"),
        ("no url here", None),
        (None, None),
    ],
)
def test_extract_page_url(text, url):
    assert extract_page_url(text) == url


def test_attach_card_setting():
    assert load_notify_config().discord.attach_card is False  # 出荷時はリンクと文章だけ
    assert DiscordConfig().attach_card is False
    assert DiscordConfig(attach_card=True).attach_card is True
