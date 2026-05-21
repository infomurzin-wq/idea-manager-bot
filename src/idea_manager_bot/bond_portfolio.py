from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any
import json
import re


PORTFOLIO_SORTS = {
    "maturity_asc",
    "maturity_desc",
    "rating_desc",
    "rating_asc",
    "coupon_desc",
    "coupon_asc",
    "sum_desc",
    "sum_asc",
}
DEFAULT_PORTFOLIO_SORT = "sum_desc"
MONTH_NAMES = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    temp_path.replace(path)


def render_portfolio_screen(snapshot: dict[str, Any], *, sort: str = DEFAULT_PORTFOLIO_SORT) -> dict[str, Any]:
    normalized_sort = normalize_portfolio_sort(sort)
    positions = sort_positions(snapshot.get("positions", []), normalized_sort)
    lines = [
        "Портфель облигаций",
        f"Срез: {snapshot.get('fetched_at', 'н/д')}",
        f"Счёт: {snapshot.get('account_id', 'н/д')}",
        f"Позиций: {len(positions)}",
        f"Сортировка: {portfolio_sort_label(normalized_sort)}",
        "",
    ]
    if not positions:
        lines.append("Облигации в портфеле не найдены.")
    for index, item in enumerate(positions, start=1):
        lines.extend(format_position(index, item))
    return {
        "text": "\n".join(lines).strip(),
        "buttons": [
            [
                button("Погашение", next_portfolio_sort("maturity", normalized_sort)),
                button("Рейтинг", next_portfolio_sort("rating", normalized_sort)),
            ],
            [
                button("Ставка", next_portfolio_sort("coupon", normalized_sort)),
                button("Сумма", next_portfolio_sort("sum", normalized_sort)),
            ],
            [button("Обновить", normalized_sort)],
            [{"text": "Cashflow", "callback_data": "bond:cashflow"}],
            [{"text": "К облигациям", "callback_data": "bond:home"}, {"text": "Главное меню", "callback_data": "main:home"}],
        ],
    }


def render_cashflow_screen(snapshot: dict[str, Any]) -> dict[str, Any]:
    events = sorted(snapshot.get("events", []), key=lambda event: (event.get("date") or "", event.get("type") or "", event.get("name") or ""))
    lines = [
        "Cashflow на 3 месяца",
        f"Срез: {snapshot.get('fetched_at', 'н/д')}",
        "",
    ]
    if not events:
        lines.append("Предстоящие выплаты по облигациям на 3 месяца не найдены.")
    coupon_total = 0.0
    principal_total = 0.0
    for month_key, month_events in group_events_by_month(events).items():
        month_total = sum(numeric_sort_value(event.get("amount")) or 0.0 for event in month_events)
        lines.append(f"{format_month_key(month_key)}:")
        for event in month_events:
            amount = numeric_sort_value(event.get("amount")) or 0.0
            if event.get("type") == "coupon":
                coupon_total += amount
            else:
                principal_total += amount
            lines.append(
                f"- {format_event_day(event.get('date'))} {cashflow_type_label(event.get('type'))} "
                f"{event.get('name') or 'Облигация'}: {display_money(amount, event.get('currency'))}"
            )
        lines.append(f"Всего: {display_money(month_total, month_currency(month_events))}")
        lines.append("")
    if events:
        lines.extend(
            [
                "Итого:",
                f"Купоны: {display_money(coupon_total, total_currency(events))}",
                f"Амортизация/погашение: {display_money(principal_total, total_currency(events))}",
            ]
        )
    return {
        "text": "\n".join(lines).strip(),
        "buttons": [
            [{"text": "Обновить Cashflow", "callback_data": "bond:cashflow"}],
            [{"text": "Портфель", "callback_data": "bond:portfolio"}, {"text": "К облигациям", "callback_data": "bond:home"}],
            [{"text": "Главное меню", "callback_data": "main:home"}],
        ],
    }


def format_position(index: int, item: dict[str, Any]) -> list[str]:
    name = item.get("name") or item.get("isin") or item.get("figi") or "Облигация"
    isin = item.get("isin") or "ISIN н/д"
    quantity = display_number(item.get("quantity"))
    position_sum = display_money(item.get("position_sum"), item.get("currency"))
    coupon_rate = display_percent(item.get("coupon_rate"))
    maturity = display_date(item.get("maturity_date"))
    rating = item.get("rating") or "н/д"
    return [
        f"{index}. {name}",
        f"   ISIN: {isin}",
        f"   Кол-во: {quantity} | Сумма: {position_sum}",
        f"   Ставка: {coupon_rate} | Погашение: {maturity} | Рейтинг: {rating}",
        "",
    ]


def sort_positions(positions: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    normalized_sort = normalize_portfolio_sort(sort)
    field, direction = normalized_sort.rsplit("_", 1)
    reverse = direction == "desc"
    key_functions = {
        "maturity": maturity_sort_value,
        "rating": rating_sort_value,
        "coupon": lambda item: numeric_sort_value(item.get("coupon_rate")),
        "sum": lambda item: numeric_sort_value(item.get("position_sum")),
    }
    known: list[tuple[float, str, dict[str, Any]]] = []
    missing: list[tuple[str, dict[str, Any]]] = []
    for item in positions:
        value = key_functions[field](item)
        title = str(item.get("name") or item.get("isin") or "")
        if value is None:
            missing.append((title, item))
        else:
            known.append((value, title, item))
    known.sort(key=lambda row: (row[0], row[1]), reverse=reverse)
    missing.sort(key=lambda row: row[0])
    return [item for _, _, item in known] + [item for _, item in missing]


def normalize_portfolio_sort(sort: str | None) -> str:
    if sort == "yield_desc":
        return "coupon_desc"
    if sort == "yield_asc":
        return "coupon_asc"
    if sort in PORTFOLIO_SORTS:
        return sort
    return DEFAULT_PORTFOLIO_SORT


def next_portfolio_sort(field: str, current_sort: str) -> str:
    if current_sort == f"{field}_desc":
        next_sort = f"{field}_asc"
    elif current_sort == f"{field}_asc":
        next_sort = f"{field}_desc"
    else:
        default_direction = "asc" if field == "maturity" else "desc"
        next_sort = f"{field}_{default_direction}"
    return f"bond:portfolio:{next_sort}"


def portfolio_sort_label(sort: str) -> str:
    labels = {
        "maturity_asc": "погашение ближе",
        "maturity_desc": "погашение дальше",
        "rating_desc": "рейтинг выше",
        "rating_asc": "рейтинг ниже",
        "coupon_desc": "ставка купона больше",
        "coupon_asc": "ставка купона меньше",
        "sum_desc": "сумма позиции больше",
        "sum_asc": "сумма позиции меньше",
    }
    return labels[normalize_portfolio_sort(sort)]


def maturity_sort_value(item: dict[str, Any]) -> float | None:
    raw = item.get("maturity_date")
    if not raw:
        return None
    try:
        return float(date.fromisoformat(str(raw)[:10]).toordinal())
    except ValueError:
        return None


def rating_sort_value(item: dict[str, Any]) -> float | None:
    rating = item.get("rating")
    if not rating:
        return None
    normalized = str(rating).upper().replace("А", "A").replace("В", "B").replace("С", "C")
    normalized = normalized.replace("RU", "").strip()
    if "AAA" in normalized:
        value = 10.0
    elif "AA" in normalized:
        value = 9.0
    elif "A" in normalized:
        value = 8.0
    elif "BBB" in normalized:
        value = 7.0
    elif "BB" in normalized:
        value = 6.0
    elif "B" in normalized:
        value = 4.0
    else:
        return None
    if "+" in normalized:
        value += 0.3
    if "-" in normalized:
        value -= 0.3
    return value


def numeric_sort_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value))
    return float(match.group(0).replace(",", ".")) if match else None


def display_number(value: Any) -> str:
    if value is None:
        return "н/д"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def display_money(value: Any, currency: str | None) -> str:
    number = numeric_sort_value(value)
    if number is None:
        return "н/д"
    suffix = currency_suffix(currency)
    if number.is_integer():
        amount = f"{int(number):,}".replace(",", " ")
    else:
        amount = f"{number:,.2f}".replace(",", " ")
    return amount + suffix


def currency_suffix(currency: str | None) -> str:
    if not currency:
        return ""
    if str(currency).lower() in {"rub", "rur"}:
        return " ₽"
    return f" {currency}"


def display_percent(value: Any) -> str:
    number = numeric_sort_value(value)
    if number is None:
        return "н/д"
    return f"{number:.2f}%"


def display_date(value: Any) -> str:
    if not value:
        return "н/д"
    text = str(value)
    try:
        parsed = date.fromisoformat(text[:10])
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return text


def group_events_by_month(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        event_date = str(event.get("date") or "")
        if len(event_date) >= 7:
            grouped[event_date[:7]].append(event)
    return dict(sorted(grouped.items()))


def format_month_key(value: str) -> str:
    try:
        year, month = value.split("-", 1)
        return f"{MONTH_NAMES[int(month)]} {year}"
    except (ValueError, KeyError):
        return value


def format_event_day(value: Any) -> str:
    text = str(value or "")
    try:
        parsed = date.fromisoformat(text[:10])
        return parsed.strftime("%d.%m")
    except ValueError:
        return text


def cashflow_type_label(value: Any) -> str:
    if value == "coupon":
        return "Купон"
    if value == "amortization":
        return "Амортизация"
    if value == "maturity":
        return "Погашение"
    return "Выплата"


def month_currency(events: list[dict[str, Any]]) -> str | None:
    return events[0].get("currency") if events else None


def total_currency(events: list[dict[str, Any]]) -> str | None:
    currencies = {event.get("currency") for event in events if event.get("currency")}
    return currencies.pop() if len(currencies) == 1 else None


def button(text: str, sort: str) -> dict[str, str]:
    return {"text": text, "callback_data": sort if sort.startswith("bond:") else f"bond:portfolio:{sort}"}
