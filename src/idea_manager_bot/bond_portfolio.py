from __future__ import annotations

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
            [{"text": "К облигациям", "callback_data": "bond:home"}, {"text": "Главное меню", "callback_data": "main:home"}],
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
    suffix = f" {currency}" if currency else ""
    return f"{number:,.2f}".replace(",", " ") + suffix


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


def button(text: str, sort: str) -> dict[str, str]:
    return {"text": text, "callback_data": sort if sort.startswith("bond:") else f"bond:portfolio:{sort}"}
