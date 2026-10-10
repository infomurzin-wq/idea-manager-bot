"""Railway-side inbox for Codex research; no model calls here."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta
import json
import os
import sys
from types import SimpleNamespace

from telegram import Bot

from idea_manager_bot.config import load_settings
from idea_manager_bot.idea_radar import IdeaRadar, MSK, current_slot
from idea_manager_bot.idea_research import CONTEXT, SOURCES, public_url, validate_card

HOURS = (11, 16, 21)


def context(radar: IdeaRadar, now: datetime) -> dict:
    if radar.enabled or radar.source != "codex":
        raise ValueError("Codex mode is not active on Railway")
    slot = current_slot(now)
    if slot is None:
        raise ValueError("Outside a scheduled radar window")
    memory = radar.store.memory()
    topics = radar.store.topics(memory, slot)
    row = radar.store.run(slot.isoformat())
    return {
        "slot": slot.isoformat(), "state": row["state"] if row else None,
        "paused": radar.store.setting("paused") == "1", "topics": topics,
        "sources": {name: SOURCES[name] for name in topics},
        "project_context": CONTEXT, "memory": memory,
    }


def validate_submission(data: dict, now: datetime) -> tuple[datetime, dict]:
    if not isinstance(data, dict) or not isinstance(data.get("slot"), str):
        raise ValueError("Missing slot")
    slot = datetime.fromisoformat(data["slot"])
    if slot.tzinfo is None or slot.utcoffset() != timedelta(hours=3) or slot.hour not in HOURS or any((slot.minute, slot.second, slot.microsecond)):
        raise ValueError("Invalid Moscow slot")
    if not -timedelta(minutes=20) <= now.astimezone(MSK) - slot <= timedelta(hours=1):
        raise ValueError("Stale or future slot")
    reason = data.get("reason")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise ValueError("Missing editorial reason")
    topics = data.get("topics")
    if not isinstance(topics, list) or not 2 <= len(topics) <= 4 or any(not isinstance(t, str) or t not in SOURCES for t in topics) or len(set(topics)) != len(topics):
        raise ValueError("Invalid scanned topics")
    urls = data.get("consulted_urls")
    if not isinstance(urls, list) or not 1 <= len(urls) <= 80 or any(not public_url(url) for url in urls):
        raise ValueError("Invalid consulted URLs")
    evidence = data.get("evidence", "")
    if not isinstance(evidence, str) or len(evidence) > 12000:
        raise ValueError("Invalid evidence note")
    idea = data.get("idea")
    if idea is not None:
        idea = validate_card(idea, set(urls))
        if idea["topic"] not in topics:
            raise ValueError("Idea topic was not scanned")
    report = {"idea": idea, "reason": reason, "topics": topics,
              "consulted_urls": urls, "evidence": evidence, "producer": "codex"}
    return slot, report


async def publish(radar: IdeaRadar, data: dict, now: datetime) -> str:
    if radar.enabled or radar.source != "codex":
        raise ValueError("Codex mode is not active on Railway")
    if radar.store.setting("paused") == "1":
        raise ValueError("Radar is paused")
    slot, report = validate_submission(data, now)
    key = slot.isoformat()
    row = radar.store.run(key)
    if row:
        if row["state"] == "sent":
            return "already_sent"
        if row["state"] != "ready" or json.loads(row["report"] or "{}").get("producer") != "codex":
            return f"already_{row['state']}"
    else:
        if not radar.store.claim(key):
            return "already_claimed"
        radar.store.complete(key, report)
    if now.astimezone(MSK) < slot:
        return "queued"
    async with Bot(load_settings().telegram_bot_token) as bot:
        delivered = await radar.deliver(bot, key, slot)
    if not delivered:
        raise RuntimeError("Telegram delivery uncertain; check archive before retry")
    return "sent"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("context", "publish"))
    args = parser.parse_args()
    radar = IdeaRadar(load_settings(), SimpleNamespace(client=None))
    now = datetime.now(MSK)
    if args.action == "context":
        print(json.dumps(context(radar, now), ensure_ascii=False))
        return
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError("Report exceeds 64 KiB")
    status = asyncio.run(publish(radar, json.loads(raw), now))
    print(json.dumps({"status": status}))


if __name__ == "__main__":
    main()
