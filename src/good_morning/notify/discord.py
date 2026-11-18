"""Discord への通知（Webhook）

ユーザーが別プロジェクトで使っている構成と、Discord の公式ドキュメントに合わせている:
- 送るのは content（2000字まで）。メンションは allowed_mentions={"parse": []} で全部止める。
- User-Agent を必ず付ける（付けないと Discord の手前の Cloudflare に 403 で弾かれる）。
- Webhook の URL は環境変数 DISCORD_WEBHOOK_URL からだけ読む。未設定なら送らずに理由を返す。
- 失敗しても例外を投げず、理由を返す。理由に URL（＝トークン）は入れない（HTTP は状態コード、
  それ以外は例外の型名を原因までたどったもの）。タイムアウトは10秒。
- 429 のときは retry_after 秒（上限あり）待って1回だけ再送する。
- 同じ日に2回送らないよう、送れたら outputs/.notified/YYYY-MM-DD に記録する。
- 画像（カード）は multipart/form-data で添付する（payload_json と files[0]）。添付した画像は、
  flags の SUPPRESS_EMBEDS（リンクのプレビューを出さない）を付けても表示される。
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel, Field

from good_morning.errors import cause_chain
from good_morning.net import ssl_context
from good_morning.paths import CONFIG_DIR, OUTPUTS_DIR

logger = logging.getLogger(__name__)

WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
USER_AGENT = "good-morning/0.1 (morning report)"
TIMEOUT_SECONDS = 10
MAX_CONTENT_CHARS = 1900  # 上限は2000字。余裕を持たせる
FLAG_SUPPRESS_EMBEDS = 1 << 2
FLAG_SUPPRESS_NOTIFICATIONS = 1 << 12


class DiscordConfig(BaseModel):
    attach_card: bool = True
    suppress_embeds: bool = True
    silent: bool = False
    retry_on_429: bool = True
    max_retry_wait_seconds: float = 30


class NotifyConfig(BaseModel):
    discord: DiscordConfig = Field(default_factory=DiscordConfig)


def load_notify_config(config_path: Path | None = None) -> NotifyConfig:
    config_path = config_path or CONFIG_DIR / "notify.yaml"
    with open(config_path, encoding="utf-8") as f:
        return NotifyConfig(**(yaml.safe_load(f) or {}))


@dataclass(frozen=True)
class NotifyResult:
    sent: bool
    reason: str


def truncate(content: str, limit: int = MAX_CONTENT_CHARS) -> str:
    return content if len(content) <= limit else content[: limit - 1] + "…"


def build_payload(content: str, config: DiscordConfig) -> dict:
    payload: dict = {"content": truncate(content), "allowed_mentions": {"parse": []}}
    flags = (FLAG_SUPPRESS_EMBEDS if config.suppress_embeds else 0) | (
        FLAG_SUPPRESS_NOTIFICATIONS if config.silent else 0
    )
    if flags:
        payload["flags"] = flags
    return payload


def _retry_after(response) -> float:
    try:
        return float(response.json().get("retry_after", 1.0))
    except (ValueError, AttributeError, TypeError):
        return 1.0


def _request_body(payload: dict, image: Path | None) -> dict:
    """httpx.post に渡す本文。画像があれば multipart（payload_json と files[0]）、なければ JSON"""
    if image is None:
        return {"json": payload}
    return {
        "data": {"payload_json": json.dumps(payload, ensure_ascii=False)},
        "files": {"files[0]": (image.name, image.read_bytes(), "image/png")},
    }


def send_discord(
    content: str,
    config: DiscordConfig | None = None,
    webhook_url: str | None = None,
    sleep=time.sleep,
    image: Path | None = None,
) -> NotifyResult:
    """Discord に送る（image があれば添付する）。失敗しても例外は投げず、理由を返す"""
    config = config or load_notify_config().discord
    url = webhook_url or os.environ.get(WEBHOOK_ENV, "").strip()
    if not url:
        return NotifyResult(False, f"{WEBHOOK_ENV} が設定されていないため送りません")

    payload = build_payload(content, config)
    try:
        body = _request_body(payload, image)
    except OSError as e:
        logger.warning("Discord: 画像を読めないため文字だけで送ります（%s）", type(e).__name__)
        body = _request_body(payload, None)
    for attempt in (1, 2):
        try:
            response = httpx.post(
                url,
                params={"wait": "true"},
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT_SECONDS,
                verify=ssl_context(),
                **body,
            )
        except Exception as e:  # noqa: BLE001 - 通知の失敗でレポートは止めない。理由だけ返す
            return NotifyResult(False, f"Discord に接続できませんでした（{cause_chain(e)}）")

        if response.status_code in (200, 204):
            return NotifyResult(True, "送信しました")
        if response.status_code == 429 and attempt == 1 and config.retry_on_429:
            wait = min(_retry_after(response), config.max_retry_wait_seconds)
            logger.warning("Discord: 429 のため %.1f 秒待って再送します", wait)
            sleep(wait)
            continue
        return NotifyResult(False, f"Discord が HTTP {response.status_code} を返しました")
    return NotifyResult(False, "Discord への再送も失敗しました")


def sent_marker(day: date, outputs_dir: Path | None = None) -> Path:
    return (outputs_dir or OUTPUTS_DIR) / ".notified" / f"{day.isoformat()}.discord"


def notify_once(
    content: str, day: date, force: bool = False, outputs_dir: Path | None = None, **kwargs
) -> NotifyResult:
    """その日まだ送っていなければ送る（force=True なら送り直す）。送れたら記録する"""
    marker = sent_marker(day, outputs_dir)
    if marker.exists() and not force:
        return NotifyResult(False, f"{day.isoformat()} の分は送信済みのため送りません（--force-notify で再送）")

    result = send_discord(content, **kwargs)
    if result.sent:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("sent\n", encoding="utf-8")
    return result
