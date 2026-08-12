"""Relay sanitized funded-tennis hourly health from KZ to Telegram.

This module has no trading endpoints. It reads a public operational-health
document and sends only non-financial liveness/capacity fields.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from telegram.error import TelegramError
from telegram.ext import Application


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _value(source: Any, *keys: str, default: Any = "n/a") -> Any:
    if not isinstance(source, dict):
        return default
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


def _heartbeat(health: dict[str, Any]) -> dict[str, Any]:
    heartbeat = health.get("railway_heartbeat")
    return heartbeat if isinstance(heartbeat, dict) else {}


def _state_key(health: dict[str, Any]) -> str | None:
    heartbeat = _heartbeat(health)
    alert_id = heartbeat.get("alert_id") or heartbeat.get("id")
    received_at = heartbeat.get("received_at") or heartbeat.get("timestamp")
    if not alert_id and not received_at:
        return None
    return f"{alert_id or ''}:{received_at or ''}"


def _format_report(health: dict[str, Any]) -> str:
    heartbeat = _heartbeat(health)
    payload = heartbeat.get("payload")
    if not isinstance(payload, dict):
        payload = heartbeat
    pool = health.get("execution_pool") or payload.get("execution_pool") or {}
    publisher = health.get("publisher") or payload.get("publisher") or {}

    active = _value(pool, "active_executions", "active")
    free = _value(pool, "free_slots", "available_slots")
    total = _value(pool, "total_slots", "capacity")
    slots = f"{free}/{total}" if free != "n/a" or total != "n/a" else "n/a"

    return "\n".join(
        [
            "<b>Funded-tennis: часовой статус</b>",
            f"Railway: {_value(payload, 'railway_status', 'status', default=_value(publisher, 'status'))}",
            f"Целей в потоке: {_value(payload, 'targets', 'tracked_targets')}",
            f"Готовых сигналов: {_value(payload, 'execution_ready', 'ready_candidates')}",
            f"Кандидатов сегодня: {_value(payload, 'candidates_today')}",
            f"Исполнение: active={active}, слоты={slots}",
            f"Новые исполнения: {_value(health, 'accepting_new_executions', default=_value(payload, 'accepting_new_executions'))}",
            f"Аварийная остановка: {_value(health, 'global_emergency', default=_value(payload, 'global_emergency'))}",
            f"Снимок KZ: {_value(heartbeat, 'received_at', 'timestamp')}",
        ]
    )


class PmaHourlyReporter:
    def __init__(self, application: Application) -> None:
        self.application = application
        self.health_url = os.getenv("PMA_KZ_HEALTH_URL", "").strip()
        self.chat_id = os.getenv("PMA_OPERATOR_CHAT_ID", "").strip()
        self.poll_seconds = max(float(os.getenv("PMA_HOURLY_POLL_SECONDS", "60")), 15.0)
        data_dir = Path(os.getenv("BOT_DATA_DIR", "data"))
        self.state_path = data_dir / "pma-hourly-relay-state.json"

    @property
    def configured(self) -> bool:
        return bool(
            _enabled(os.getenv("PMA_HOURLY_REPORTS_ENABLED"))
            and self.health_url
            and self.chat_id
        )

    def _load_key(self) -> str | None:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value.get("last_sent_key") or value.get("baseline_key")
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            return None

    def _save_key(self, key: str, *, sent: bool) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        target = self.state_path.with_suffix(".tmp")
        field = "last_sent_key" if sent else "baseline_key"
        target.write_text(
            json.dumps(
                {field: key, "updated_at": datetime.now(timezone.utc).isoformat()},
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        os.replace(target, self.state_path)

    async def run(self) -> None:
        if not self.configured:
            return
        known_key = self._load_key()
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                try:
                    response = await client.get(self.health_url)
                    response.raise_for_status()
                    health = response.json()
                    key = _state_key(health)
                    if key and known_key is None:
                        # Establish a baseline on first start; never replay old reports.
                        self._save_key(key, sent=False)
                        known_key = key
                    elif key and key != known_key:
                        await self.application.bot.send_message(
                            chat_id=self.chat_id,
                            text=_format_report(health),
                            parse_mode="HTML",
                        )
                        self._save_key(key, sent=True)
                        known_key = key
                except (httpx.HTTPError, TelegramError, ValueError, OSError):
                    pass
                await asyncio.sleep(self.poll_seconds)


def start_pma_hourly_reporter(application: Application) -> None:
    reporter = PmaHourlyReporter(application)
    if reporter.configured:
        application.bot_data["pma_hourly_reporter"] = reporter
        application.bot_data["pma_hourly_reporter_task"] = application.create_task(
            reporter.run(),
            name="pma-hourly-reporter",
        )
