#!/usr/bin/env python3
"""Offline Telegram action adapter for Bond Radar candidate screens."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import candidate_store
import format_candidate


ACTION_HOME = "bond:home"
ACTION_MAIN_MENU = "main:home"
STATUS_ACTIONS = {
    "bond:list:new": "new",
    "bond:list:watchlist": "watchlist",
    "bond:list:rejected": "rejected",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Render offline Telegram action responses for Bond Radar.")
    parser.add_argument("action", help="Callback action, for example bond:home, bond:list:new, bond:show:<key>.")
    parser.add_argument("--store", type=Path, default=candidate_store.DEFAULT_STORE_PATH, help="JSONL candidate store path.")
    parser.add_argument("--format", choices=("text", "json"), default="json")
    args = parser.parse_args()

    screen = handle_action(args.action, args.store)
    if args.format == "text":
        print(screen["text"])
        return

    print(json.dumps(screen, ensure_ascii=False, sort_keys=True, indent=2))


def handle_action(action: str, store_path: Path = candidate_store.DEFAULT_STORE_PATH) -> dict[str, Any]:
    """Return a Telegram-like screen payload for a Bond Radar callback action."""
    records = candidate_store.load_store(store_path)

    if action == ACTION_HOME:
        return home_screen(records)

    if action in STATUS_ACTIONS:
        return list_screen(records, STATUS_ACTIONS[action])

    if action.startswith("bond:show:"):
        key = resolve_action_key(records, action.removeprefix("bond:show:"))
        return show_screen(records, key)

    if action.startswith("bond:watch:"):
        key = resolve_action_key(records, action.removeprefix("bond:watch:"))
        record = candidate_store.set_candidate_status(records, key, "watchlist")
        candidate_store.write_store(store_path, records)
        return show_screen(records, record["storage"]["key"], prefix="Добавлено в Watchlist.")

    if action.startswith("bond:reject:"):
        key = resolve_action_key(records, action.removeprefix("bond:reject:"))
        record = candidate_store.set_candidate_status(records, key, "rejected")
        candidate_store.write_store(store_path, records)
        return show_screen(records, record["storage"]["key"], prefix="Кандидат отклонен.")

    return {
        "text": f"Неизвестное действие: {action}",
        "buttons": [[button("К облигациям", ACTION_HOME), button("Главное меню", ACTION_MAIN_MENU)]],
    }


def home_screen(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    counts = count_by_status(records)
    text = (
        "Облигации\n\n"
        f"Новые кандидаты: {counts['new']}\n"
        f"Watchlist: {counts['watchlist']}\n"
        f"Отклоненные: {counts['rejected']}\n\n"
        "Выбери раздел."
    )
    return {
        "text": text,
        "buttons": [
            [button(f"Новые кандидаты ({counts['new']})", "bond:list:new")],
            [button(f"Watchlist ({counts['watchlist']})", "bond:list:watchlist")],
            [button(f"Отклоненные ({counts['rejected']})", "bond:list:rejected")],
            [button("Главное меню", ACTION_MAIN_MENU)],
        ],
    }


def list_screen(records: dict[str, dict[str, Any]], status: str) -> dict[str, Any]:
    items = candidate_store.list_candidates(records, status=status)
    text = format_candidate.format_candidate_list_message(items, status=status)
    buttons = list_candidate_buttons(items)
    buttons.extend([[button("К облигациям", ACTION_HOME), button("Главное меню", ACTION_MAIN_MENU)]])
    return {"text": text, "buttons": buttons}


def show_screen(records: dict[str, dict[str, Any]], key: str, *, prefix: str | None = None) -> dict[str, Any]:
    record = candidate_store.get_candidate(records, key)
    text = format_candidate.format_candidate_message(record)
    if prefix:
        text = f"{prefix}\n\n{text}"
    return {"text": text, "buttons": detail_buttons(record)}


def detail_buttons(record: dict[str, Any]) -> list[list[dict[str, str]]]:
    key = record["storage"]["key"]
    short_id = short_callback_id(key)
    status = record["storage"]["status"]
    rows: list[list[dict[str, str]]] = []

    if status == "new":
        rows.append([button("В watchlist", f"bond:watch:{short_id}"), button("Отклонить", f"bond:reject:{short_id}")])
    elif status == "watchlist":
        rows.append([button("Отклонить", f"bond:reject:{short_id}")])
    elif status == "rejected":
        rows.append([button("В watchlist", f"bond:watch:{short_id}")])

    rows.append([button("Назад", f"bond:list:{status}"), button("Главное меню", ACTION_MAIN_MENU)])
    return rows


def list_candidate_buttons(records: list[dict[str, Any]], *, limit: int = 20) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    for index, record in enumerate(records[:limit], start=1):
        title = candidate_button_title(index, record)
        rows.append([button(title, f"bond:show:{short_callback_id(record['storage']['key'])}")])
    return rows


def candidate_button_title(index: int, record: dict[str, Any]) -> str:
    candidate = record["candidate"]
    title = format_candidate.format_title(candidate["instrument"])
    return f"{index}. {title}"


def count_by_status(records: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in candidate_store.VALID_STATUSES}
    for record in records.values():
        status = record["storage"]["status"]
        if status in counts:
            counts[status] += 1
    return counts


def resolve_action_key(records: dict[str, dict[str, Any]], value: str) -> str:
    """Resolve a short Telegram callback id or a regular candidate lookup key."""
    for key in records:
        if short_callback_id(key) == value:
            return key
    return value


def short_callback_id(key: str) -> str:
    """Return a compact stable id that fits Telegram callback_data limits."""
    return hashlib.blake2s(key.encode("utf-8"), digest_size=6).hexdigest()


def button(text: str, action: str) -> dict[str, str]:
    return {"text": text, "callback_data": action}


if __name__ == "__main__":
    main()
