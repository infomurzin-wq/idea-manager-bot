#!/usr/bin/env python3
"""Offline Telegram action adapter for Bond Radar candidate screens."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import candidate_store
import format_candidate


ACTION_HOME = "bond:home"
ACTION_MAIN_MENU = "main:home"
ACTION_ADD_MANUAL = "bond:add:manual"
STATUS_ACTIONS = {
    "bond:list:new": "new",
    "bond:list:watchlist": "watchlist",
    "bond:list:rejected": "rejected",
}
PAGE_SIZE = 10
DEFAULT_SORT = "default"
VALID_SORTS = {
    DEFAULT_SORT,
    "ytm_desc",
    "ytm_asc",
    "maturity_desc",
    "maturity_asc",
    "rating_desc",
    "rating_asc",
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

    parsed_list_action = parse_list_action(action)
    if parsed_list_action is not None:
        status, page, sort = parsed_list_action
        return list_screen(records, status, page=page, sort=sort)

    if action == ACTION_ADD_MANUAL:
        return {
            "text": (
                "Добавить кандидата вручную\n\n"
                "Отправь следующим сообщением текст поста или параметры выпуска. "
                "Бот попробует извлечь карточку и добавить ее в Новые кандидаты."
            ),
            "buttons": [[button("К облигациям", ACTION_HOME), button("Главное меню", ACTION_MAIN_MENU)]],
        }

    if action.startswith("bond:show:"):
        origin, value = parse_origin_and_key(action.removeprefix("bond:show:"))
        key = resolve_action_key(records, value)
        return show_screen(records, key, origin=origin)

    if action.startswith("bond:watch:"):
        origin, value = parse_origin_and_key(action.removeprefix("bond:watch:"))
        key = resolve_action_key(records, value)
        record = candidate_store.set_candidate_status(records, key, "watchlist")
        candidate_store.write_store(store_path, records)
        return show_screen(
            records,
            record["storage"]["key"],
            prefix="Добавлено в Watchlist.",
            origin=origin,
        )

    if action.startswith("bond:reject:"):
        origin, value = parse_origin_and_key(action.removeprefix("bond:reject:"))
        key = resolve_action_key(records, value)
        record = candidate_store.set_candidate_status(records, key, "rejected")
        candidate_store.write_store(store_path, records)
        return show_screen(
            records,
            record["storage"]["key"],
            prefix="Кандидат отклонен.",
            origin=origin,
        )

    if action.startswith("bond:delete-confirm:"):
        origin, value = parse_origin_and_key(action.removeprefix("bond:delete-confirm:"))
        key = resolve_action_key(records, value)
        record = candidate_store.get_candidate(records, key)
        title = format_candidate.format_title(record["candidate"]["instrument"])
        back_status, back_page, back_sort = back_target(origin, record["storage"]["status"])
        candidate_store.delete_candidate(records, key)
        candidate_store.write_store(store_path, records)
        screen = list_screen(records, back_status, page=back_page, sort=back_sort)
        screen["text"] = f"Карточка удалена: {title}\n\n{screen['text']}"
        return screen

    if action.startswith("bond:delete:"):
        origin, value = parse_origin_and_key(action.removeprefix("bond:delete:"))
        key = resolve_action_key(records, value)
        record = candidate_store.get_candidate(records, key)
        return delete_confirm_screen(record, origin=origin)

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
            [button("Добавить вручную", ACTION_ADD_MANUAL)],
            [button(f"Watchlist ({counts['watchlist']})", "bond:list:watchlist")],
            [button(f"Отклоненные ({counts['rejected']})", "bond:list:rejected")],
            [button("Главное меню", ACTION_MAIN_MENU)],
        ],
    }


def list_screen(
    records: dict[str, dict[str, Any]],
    status: str,
    *,
    page: int = 1,
    sort: str = DEFAULT_SORT,
) -> dict[str, Any]:
    items = sort_candidates(candidate_store.list_candidates(records, status=status), sort)
    page_count = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    current_page = min(max(1, page), page_count)
    offset = (current_page - 1) * PAGE_SIZE
    page_items = items[offset : offset + PAGE_SIZE]
    text = format_candidate.format_candidate_list_message(
        page_items,
        status=status,
        total_count=len(items),
        offset=offset,
        page=current_page,
        page_count=page_count,
    )
    origin = origin_token(status, current_page, sort)
    buttons = list_candidate_buttons(page_items, origin=origin, start_index=offset + 1)
    buttons.insert(0, sort_buttons(status, sort))
    if status == "new":
        buttons.insert(1, [button("Добавить вручную", ACTION_ADD_MANUAL)])
    pagination = pagination_buttons(status, current_page, page_count, sort)
    if pagination:
        buttons.append(pagination)
    buttons.extend([[button("К облигациям", ACTION_HOME), button("Главное меню", ACTION_MAIN_MENU)]])
    return {"text": text, "buttons": buttons}


def show_screen(
    records: dict[str, dict[str, Any]],
    key: str,
    *,
    prefix: str | None = None,
    origin: str | None = None,
) -> dict[str, Any]:
    record = candidate_store.get_candidate(records, key)
    text = format_candidate.format_candidate_message(record)
    if prefix:
        text = f"{prefix}\n\n{text}"
    return {"text": text, "buttons": detail_buttons(record, origin=origin)}


def detail_buttons(record: dict[str, Any], *, origin: str | None = None) -> list[list[dict[str, str]]]:
    key = record["storage"]["key"]
    short_id = short_callback_id(key)
    status = record["storage"]["status"]
    back_status, back_page, back_sort = back_target(origin, status)
    encoded_origin = origin_token(back_status, back_page, back_sort)
    rows: list[list[dict[str, str]]] = []

    if status == "new":
        rows.append(
            [
                button("В watchlist", f"bond:watch:{encoded_origin}:{short_id}"),
                button("Отклонить", f"bond:reject:{encoded_origin}:{short_id}"),
            ]
        )
    elif status == "watchlist":
        rows.append([button("Отклонить", f"bond:reject:{encoded_origin}:{short_id}")])
    elif status == "rejected":
        rows.append([button("В watchlist", f"bond:watch:{encoded_origin}:{short_id}")])
        rows.append([button("Удалить", f"bond:delete:{encoded_origin}:{short_id}")])

    rows.append([button("Назад", list_action(back_status, back_page, back_sort)), button("Главное меню", ACTION_MAIN_MENU)])
    return rows


def delete_confirm_screen(record: dict[str, Any], *, origin: str | None = None) -> dict[str, Any]:
    key = record["storage"]["key"]
    short_id = short_callback_id(key)
    status = record["storage"]["status"]
    back_status, back_page, back_sort = back_target(origin, status)
    encoded_origin = origin_token(back_status, back_page, back_sort)
    title = format_candidate.format_title(record["candidate"]["instrument"])
    return {
        "text": (
            f"Удалить карточку: {title}?\n\n"
            "Это действие уберет запись из Bond Radar store. "
            "Используй его только для ошибочных импортов."
        ),
        "buttons": [
            [button("Удалить навсегда", f"bond:delete-confirm:{encoded_origin}:{short_id}")],
            [button("Назад", f"bond:show:{encoded_origin}:{short_id}"), button("Главное меню", ACTION_MAIN_MENU)],
        ],
    }


def list_candidate_buttons(
    records: list[dict[str, Any]],
    *,
    origin: str,
    start_index: int = 1,
) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    for index, record in enumerate(records, start=start_index):
        title = candidate_button_title(index, record)
        rows.append([button(title, f"bond:show:{origin}:{short_callback_id(record['storage']['key'])}")])
    return rows


def candidate_button_title(index: int, record: dict[str, Any]) -> str:
    candidate = record["candidate"]
    title = compact_title(format_candidate.format_title(candidate["instrument"]))
    instrument = candidate["instrument"]
    terms = candidate["terms"]
    rating = display_short(instrument.get("rating"))
    ytm = display_short(terms.get("ytm_raw") or terms.get("ytm"))
    coupon = display_short(terms.get("coupon_raw") or terms.get("coupon"))
    maturity = maturity_short(terms.get("maturity_date"))
    rate = ytm if ytm != "н/д" else coupon
    return f"{index}. {title} | {rating} | {rate} | {maturity}"


def compact_title(value: str, *, limit: int = 24) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def display_short(value: Any) -> str:
    if value is None or value == "" or value == []:
        return "н/д"
    return str(value)


def maturity_short(value: Any) -> str:
    if value is None or value == "" or value == []:
        return "н/д"
    raw = str(value)
    if match := re.fullmatch(r"(\d+(?:\.\d+)?) years", raw):
        return f"{match.group(1)}г"
    if match := re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", raw):
        return f"{match.group(1)}.{match.group(2)}.{match.group(3)[2:]}"
    return raw


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


def parse_origin_and_key(value: str) -> tuple[str | None, str]:
    origin, separator, key = value.partition(":")
    if separator and parse_origin_token(origin) is not None:
        return origin, key
    return None, value


def parse_list_action(action: str) -> tuple[str, int, str] | None:
    parts = action.split(":")
    if len(parts) not in {3, 4, 5} or parts[0] != "bond" or parts[1] != "list":
        return None
    status = parts[2]
    if status not in candidate_store.VALID_STATUSES:
        return None
    if len(parts) == 3:
        return status, 1, DEFAULT_SORT
    try:
        page = int(parts[3])
    except ValueError:
        page = 1
    sort = normalize_sort(parts[4]) if len(parts) == 5 else DEFAULT_SORT
    return status, max(1, page), sort


def pagination_buttons(status: str, page: int, page_count: int, sort: str = DEFAULT_SORT) -> list[dict[str, str]]:
    if page_count <= 1:
        return []
    row: list[dict[str, str]] = []
    if page > 1:
        row.append(button("← Назад", list_action(status, page - 1, sort)))
    if page < page_count:
        row.append(button("Дальше →", list_action(status, page + 1, sort)))
    return row


def sort_buttons(status: str, current_sort: str) -> list[dict[str, str]]:
    return [
        button(sort_label("ytm", current_sort), list_action(status, 1, next_sort("ytm", current_sort))),
        button(sort_label("maturity", current_sort), list_action(status, 1, next_sort("maturity", current_sort))),
        button(sort_label("rating", current_sort), list_action(status, 1, next_sort("rating", current_sort))),
    ]


def sort_label(field: str, current_sort: str) -> str:
    labels = {"ytm": "Доходность", "maturity": "Погашение", "rating": "Рейтинг"}
    if current_sort == f"{field}_desc":
        return f"{labels[field]} ↓"
    if current_sort == f"{field}_asc":
        return f"{labels[field]} ↑"
    return f"{labels[field]} ↑↓"


def next_sort(field: str, current_sort: str) -> str:
    if current_sort == f"{field}_desc":
        return f"{field}_asc"
    return f"{field}_desc"


def list_action(status: str, page: int, sort: str = DEFAULT_SORT) -> str:
    normalized_sort = normalize_sort(sort)
    if page <= 1 and normalized_sort == DEFAULT_SORT:
        return f"bond:list:{status}"
    if normalized_sort == DEFAULT_SORT:
        return f"bond:list:{status}:{max(1, page)}"
    return f"bond:list:{status}:{max(1, page)}:{normalized_sort}"


def origin_token(status: str, page: int = 1, sort: str = DEFAULT_SORT) -> str:
    normalized_sort = normalize_sort(sort)
    if page <= 1 and normalized_sort == DEFAULT_SORT:
        return status
    if normalized_sort == DEFAULT_SORT:
        return f"{status}~{max(1, page)}"
    return f"{status}~{max(1, page)}~{normalized_sort}"


def parse_origin_token(value: str | None) -> tuple[str, int, str] | None:
    if not value:
        return None
    parts = value.split("~")
    status = parts[0]
    if status not in candidate_store.VALID_STATUSES:
        return None
    if len(parts) == 1:
        return status, 1, DEFAULT_SORT
    try:
        page = int(parts[1])
    except ValueError:
        page = 1
    sort = normalize_sort(parts[2]) if len(parts) > 2 else DEFAULT_SORT
    return status, max(1, page), sort


def back_target(origin: str | None, fallback_status: str) -> tuple[str, int, str]:
    parsed = parse_origin_token(origin)
    if parsed is not None:
        return parsed
    return fallback_status, 1, DEFAULT_SORT


def normalize_sort(sort: str | None) -> str:
    if sort in VALID_SORTS:
        return sort
    return DEFAULT_SORT


def sort_candidates(records: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    normalized_sort = normalize_sort(sort)
    if normalized_sort == DEFAULT_SORT:
        return records

    field, direction = normalized_sort.rsplit("_", 1)
    reverse = direction == "desc"
    key_functions = {
        "ytm": ytm_sort_value,
        "maturity": maturity_sort_value,
        "rating": rating_sort_value,
    }
    known: list[tuple[float, str, dict[str, Any]]] = []
    missing: list[tuple[str, dict[str, Any]]] = []
    key_function = key_functions[field]
    for record in records:
        value = key_function(record)
        title = candidate_sort_title(record)
        if value is None:
            missing.append((title, record))
        else:
            known.append((value, title, record))

    known.sort(key=lambda item: (item[0], item[1]), reverse=reverse)
    missing.sort(key=lambda item: item[0])
    return [record for _, _, record in known] + [record for _, record in missing]


def ytm_sort_value(record: dict[str, Any]) -> float | None:
    terms = record["candidate"]["terms"]
    return parse_percent_number(terms.get("ytm") or terms.get("ytm_raw"))


def maturity_sort_value(record: dict[str, Any]) -> float | None:
    value = record["candidate"]["terms"].get("maturity_date")
    if value is None:
        return None
    if match := re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", str(value)):
        parsed = datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        return float(parsed.toordinal())
    if match := re.fullmatch(r"(\d+(?:\.\d+)?) years", str(value)):
        return float(match.group(1)) * 365.0
    return None


def rating_sort_value(record: dict[str, Any]) -> float | None:
    rating = record["candidate"]["instrument"].get("rating")
    if not rating:
        return None
    normalized = str(rating).upper().replace("А", "A").replace("В", "B").replace("С", "C")
    normalized = normalized.replace("RU", "").replace("|", "").strip()
    normalized = normalized.replace("–", "-").replace("—", "-").replace("−", "-")
    if "AAA" in normalized:
        base = 10.0
    elif "AA" in normalized:
        base = 9.0
    elif "A" in normalized:
        base = 8.0
    elif "BBB" in normalized:
        base = 7.0
    elif "BB" in normalized:
        base = 6.0
    elif "B" in normalized:
        base = 4.0
    elif "CCC" in normalized:
        base = 2.0
    elif "CC" in normalized or "C" in normalized:
        base = 1.0
    elif "D" in normalized:
        base = 0.0
    else:
        return None
    if "+" in normalized:
        base += 0.3
    if "-" in normalized:
        base -= 0.3
    return base


def parse_percent_number(value: Any) -> float | None:
    if value is None:
        return None
    matches = re.findall(r"\d+(?:[.,]\d+)?", str(value))
    if not matches:
        return None
    return max(float(match.replace(",", ".")) for match in matches)


def candidate_sort_title(record: dict[str, Any]) -> str:
    return format_candidate.format_title(record["candidate"]["instrument"]).lower()


def short_callback_id(key: str) -> str:
    """Return a compact stable id that fits Telegram callback_data limits."""
    return hashlib.blake2s(key.encode("utf-8"), digest_size=6).hexdigest()


def button(text: str, action: str) -> dict[str, str]:
    return {"text": text, "callback_data": action}


if __name__ == "__main__":
    main()
