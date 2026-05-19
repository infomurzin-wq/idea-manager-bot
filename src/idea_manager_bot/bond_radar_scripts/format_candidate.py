#!/usr/bin/env python3
"""Format stored bond candidate records for Telegram messages."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import candidate_store


STATUS_LABELS = {
    "new": "новый",
    "watchlist": "watchlist",
    "rejected": "отклонен",
}

ASSESSMENT_LABELS = {
    "interesting": "интересно",
    "needs_review": "нужна ручная проверка",
    "reject": "не подходит под базовый фильтр",
}

RED_FLAG_LABELS = {
    "floating_coupon": "плавающий купон",
    "offer_present_or_needs_review": "оферта или нужна проверка оферты",
    "amortization_present_or_needs_review": "амортизация или нужна проверка амортизации",
    "qualified_investors_only": "только для квалов",
    "rating_below_target": "рейтинг ниже базового ориентира",
    "promotional_yield_without_ytm": "рекламная доходность без YTM",
    "liquidity_or_size_risk": "риск ликвидности или размера выпуска",
    "currency_mismatch_or_fx_linked": "валютная бумага или валютная привязка",
}

MISSING_FIELD_LABELS = {
    "issuer": "эмитент",
    "coupon": "купон",
    "ytm": "YTM",
    "book_building_date": "сбор заявок",
    "placement_date": "размещение",
    "maturity_date": "погашение / срок",
    "offer": "оферта",
    "amortization": "амортизация",
    "coupon_frequency_per_year": "выплат в год",
    "coupon_type": "тип купона",
    "rating": "рейтинг",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Format stored bond candidate records as Telegram text.")
    subparsers = parser.add_subparsers(dest="command")

    card_parser = subparsers.add_parser("card", help="Format one candidate card.")
    card_parser.add_argument("key", help="storage.key, dedup key, ISIN key, or another matched candidate key.")
    card_parser.add_argument("--store", type=Path, default=candidate_store.DEFAULT_STORE_PATH, help="JSONL candidate store path.")

    list_parser = subparsers.add_parser("list", help="Format a candidate list screen.")
    list_parser.add_argument("--store", type=Path, default=candidate_store.DEFAULT_STORE_PATH, help="JSONL candidate store path.")
    list_parser.add_argument("--status", choices=sorted(candidate_store.VALID_STATUSES), default="new")
    list_parser.add_argument("--limit", type=int, default=20)

    raw_args = normalize_args()
    args = parser.parse_args(raw_args)
    if args.command is None:
        parser.error("use `card` or `list`")

    records = candidate_store.load_store(args.store)
    if args.command == "list":
        items = candidate_store.list_candidates(records, status=args.status)
        print(format_candidate_list_message(items, status=args.status, limit=args.limit))
        return

    record = candidate_store.get_candidate(records, args.key)
    print(format_candidate_message(record))


def normalize_args() -> list[str]:
    import sys

    args = sys.argv[1:]
    if args and args[0] not in {"card", "list"}:
        return ["card", *args]
    return args


def format_candidate_message(record: dict[str, Any]) -> str:
    candidate = record["candidate"]
    instrument = candidate["instrument"]
    terms = candidate["terms"]
    assessment = candidate["assessment"]
    dedup = candidate["dedup"]
    storage = record["storage"]

    title = format_title(instrument)
    lines = [
        f"Найден кандидат: {title}",
        "",
        f"Статус: {STATUS_LABELS.get(storage['status'], storage['status'])}",
        f"Предварительно: {ASSESSMENT_LABELS.get(assessment['status'], assessment['status'])}",
        "",
        f"Эмитент: {display(instrument.get('issuer'))}",
        f"Выпуск: {display(instrument.get('issue_name'))}",
        f"ISIN: {display(instrument.get('isin'))}",
        f"Рейтинг: {display(instrument.get('rating'))}",
        f"Купон: {display(terms.get('coupon_raw') or terms.get('coupon'))}",
        f"YTM: {display(terms.get('ytm_raw') or terms.get('ytm'))}",
        f"Выплат в год: {display(terms.get('coupon_frequency_per_year'))}",
        f"Тип купона: {format_coupon_type(terms.get('coupon_type'))}",
        f"Цена: {display(terms.get('price'))}",
        f"Сбор заявок: {display(terms.get('book_building_date'))}",
        f"Размещение: {display(terms.get('placement_date'))}",
        f"Первый день торгов: {display(terms.get('first_trading_date'))}",
        f"Погашение / срок: {format_maturity(terms.get('maturity_date'))}",
        f"Оферта: {display(terms.get('offer'))}",
        f"Амортизация: {display(terms.get('amortization'))}",
        f"Объем: {display(terms.get('issue_size'))}",
        f"Для квалов: {format_bool(terms.get('qualified_only'))}",
        "",
        f"Причина: {assessment.get('interest_reason') or 'нужно проверить вручную'}",
        f"Красные флаги: {format_list(assessment.get('red_flags'), RED_FLAG_LABELS)}",
        f"Не хватает: {format_list(assessment.get('missing_fields'), MISSING_FIELD_LABELS)}",
        f"Источников: {dedup.get('source_count', 1)}",
    ]

    source_lines = format_source_lines(dedup.get("sources"))
    if source_lines:
        lines.extend(["", "Источники:"])
        lines.extend(source_lines)

    if dedup.get("conflicts"):
        lines.extend(["", "Расхождения источников:"])
        for conflict in dedup["conflicts"][:5]:
            lines.append(
                f"- {conflict['field']}: было {display(conflict.get('kept'))}, "
                f"в источнике {display(conflict.get('incoming'))}"
            )

    return "\n".join(lines)


def format_candidate_list_message(
    records: list[dict[str, Any]],
    *,
    status: str,
    limit: int = 30,
    total_count: int | None = None,
    offset: int = 0,
    page: int | None = None,
    page_count: int | None = None,
) -> str:
    title = {
        "new": "Новые кандидаты",
        "watchlist": "Watchlist",
        "rejected": "Отклоненные",
    }.get(status, "Кандидаты")
    total = len(records) if total_count is None else total_count
    visible = records[:limit]
    lines = [f"{title}: {total}"]
    if page is not None and page_count is not None and page_count > 1:
        lines.append(f"Страница {page}/{page_count}")
    lines.append("")

    if not visible:
        lines.append("Список пуст.")
        return "\n".join(lines)

    for index, record in enumerate(visible, start=offset + 1):
        lines.extend(format_candidate_list_item(index, record))

    if total_count is not None and total > len(visible):
        first = offset + 1
        last = offset + len(visible)
        lines.extend(["", f"Показано {first}-{last} из {total}."])
    elif len(records) > limit:
        lines.extend(["", f"Показано {limit} из {len(records)}."])

    return "\n".join(lines).rstrip()


def format_candidate_list_item(index: int, record: dict[str, Any]) -> list[str]:
    item = candidate_store.compact_list_item(record)
    markers = []
    if item["red_flags"]:
        markers.append("флаги")
    if record["candidate"]["assessment"].get("missing_fields"):
        markers.append("неполные данные")
    suffix = f" ({', '.join(markers)})" if markers else ""

    title = " ".join(str(part) for part in (item["issuer"], item["issue_name"]) if part) or "без названия"
    details = [
        display(item["rating"]),
        f"купон {display(item['coupon'])}",
        f"YTM {display(item['ytm'])}",
        f"сбор {display(item['book_building_date'])}",
    ]
    return [
        f"{index}. {title}{suffix}",
        f"   {' | '.join(details)}",
        f"   key: {item['key']}",
    ]


def format_title(instrument: dict[str, Any]) -> str:
    parts = [instrument.get("issuer"), instrument.get("issue_name")]
    title = " ".join(str(part) for part in parts if part)
    return title or "без названия"


def display(value: Any) -> str:
    if value is None or value == "" or value == []:
        return "пока не найдено"
    return str(value)


def format_coupon_type(value: Any) -> str:
    labels = {"fixed": "фиксированный", "floating": "плавающий", "unknown": "нужно проверить"}
    return labels.get(value, display(value))


def format_bool(value: Any) -> str:
    if value is True:
        return "да"
    if value is False:
        return "нет"
    return "пока не найдено"


def format_maturity(value: Any) -> str:
    if value is None:
        return "пока не найдено"
    match = re.fullmatch(r"(\d+(?:\.\d+)?) years", str(value))
    if not match:
        return display(value)
    number = match.group(1)
    return f"{number} {year_word(number)}"


def year_word(value: str) -> str:
    if "." in value:
        return "года"
    number = int(value)
    if 11 <= number % 100 <= 14:
        return "лет"
    if number % 10 == 1:
        return "год"
    if 2 <= number % 10 <= 4:
        return "года"
    return "лет"


def format_list(values: list[str] | None, labels: dict[str, str]) -> str:
    if not values:
        return "нет"
    return ", ".join(labels.get(value, value) for value in values)


def format_source_lines(sources: list[dict[str, Any]] | None, *, limit: int = 3) -> list[str]:
    if not sources:
        return []

    lines = []
    for index, source in enumerate(sources[:limit], start=1):
        label = format_source_label(source)
        url = source.get("url")
        if url:
            lines.append(f"{index}. {label} - {url}")
        else:
            lines.append(f"{index}. {label}")

    if len(sources) > limit:
        lines.append(f"...ещё {len(sources) - limit}")

    return lines


def format_source_label(source: dict[str, Any]) -> str:
    channel = source.get("channel") or "источник"
    post_date = source.get("post_date")
    if post_date:
        return f"{channel} · {post_date}"
    return str(channel)


if __name__ == "__main__":
    main()
