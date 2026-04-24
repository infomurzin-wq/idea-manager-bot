from __future__ import annotations

import json
import mimetypes
import os
import secrets
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ReportSnapshot

TELEGRAM_API_BASE = "https://api.telegram.org"


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


def load_telegram_bot_token() -> str:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("Missing Telegram env var: TELEGRAM_BOT_TOKEN")
    return bot_token


def load_telegram_config() -> TelegramConfig:
    bot_token = load_telegram_bot_token()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        raise RuntimeError("Missing Telegram env var: TELEGRAM_CHAT_ID")
    return TelegramConfig(bot_token=bot_token, chat_id=chat_id)


def send_report_delivery(
    *,
    report: ReportSnapshot,
    markdown_path: Path,
    report_kind: str,
) -> None:
    config = load_telegram_config()
    send_message(config, build_summary_message(report=report, report_kind=report_kind))
    send_document(
        config,
        document_path=markdown_path,
        caption=build_document_caption(report=report, report_kind=report_kind),
        filename=f"{report.event.event_date}-{report.event.event_slug}-{report_kind}.md",
    )


def build_summary_message(*, report: ReportSnapshot, report_kind: str) -> str:
    if report_kind == "baseline":
        title = "UFC baseline report"
        description = "Найден турнир на ближайшие выходные. Полный Markdown-отчёт прикреплён файлом."
    else:
        title = "UFC report update"
        description = "Есть meaningful changes относительно последней отправленной версии. Обновлённый Markdown-отчёт прикреплён файлом."
    return "\n".join(
        [
            title,
            f"Турнир: {report.event.event_name}",
            f"Дата: {report.event.event_date}",
            f"Боёв: {report.event.confirmed_bouts}",
            description,
        ]
    )


def build_document_caption(*, report: ReportSnapshot, report_kind: str) -> str:
    label = "baseline" if report_kind == "baseline" else "update"
    return f"{report.event.event_name} | {report.event.event_date} | {label}"


def send_message(config: TelegramConfig, text: str) -> dict[str, Any]:
    payload = urllib.parse.urlencode(
        {
            "chat_id": config.chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    return _post_json(config, "sendMessage", payload, content_type="application/x-www-form-urlencoded")


def send_document(
    config: TelegramConfig,
    *,
    document_path: Path,
    caption: str,
    filename: str | None = None,
) -> dict[str, Any]:
    if not document_path.exists():
        raise FileNotFoundError(f"Telegram document not found: {document_path}")
    fields = {
        "chat_id": config.chat_id,
        "caption": caption,
    }
    files = {
        "document": (
            filename or document_path.name,
            document_path.read_bytes(),
            mimetypes.guess_type(document_path.name)[0] or "text/markdown",
        )
    }
    body, boundary = _multipart_body(fields=fields, files=files)
    return _post_json(
        config,
        "sendDocument",
        body,
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def get_updates(*, limit: int = 10) -> list[dict[str, Any]]:
    bot_token = load_telegram_bot_token()
    query = urllib.parse.urlencode({"limit": str(limit)})
    request = urllib.request.Request(
        f"{TELEGRAM_API_BASE}/bot{bot_token}/getUpdates?{query}",
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API call failed: getUpdates: {payload}")
    return payload.get("result", [])


def extract_chat_candidates(updates: list[dict[str, Any]]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for update in updates:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", "")).strip()
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        candidates.append(
            {
                "chat_id": chat_id,
                "type": str(chat.get("type", "")),
                "username": str(chat.get("username", "")),
                "first_name": str(chat.get("first_name", "")),
                "last_name": str(chat.get("last_name", "")),
                "last_text": str(message.get("text", "")),
            }
        )
    return candidates


def _post_json(
    config: TelegramConfig,
    method: str,
    body: bytes,
    *,
    content_type: str,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{TELEGRAM_API_BASE}/bot{config.bot_token}/{method}",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API call failed: {method}: {payload}")
    return payload


def _multipart_body(
    *,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = f"----ufc-reporter-{secrets.token_hex(16)}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for field_name, (filename, content, content_type) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary
