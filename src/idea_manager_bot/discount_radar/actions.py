from __future__ import annotations

from urllib.parse import urlparse

from idea_manager_bot.discount_radar.formatter import (
    format_check_screen,
    format_home_screen,
    format_product_list,
    product_button_label,
)
from idea_manager_bot.discount_radar.store import DiscountRadarStore, Product


def is_ozon_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = parsed.hostname or ""
    return hostname == "ozon.ru" or hostname.endswith(".ozon.ru")


def parse_price(value: str) -> int | None:
    digits = "".join(char for char in value if char.isdigit())
    if not digits:
        return None
    return int(digits)


def home_screen(store: DiscountRadarStore, user_id: int) -> dict:
    products = store.list_products(user_id)
    return {
        "text": format_home_screen(products),
        "buttons": [
            [
                {"text": "Добавить товар", "callback_data": "discount:add"},
                {"text": "Мои товары", "callback_data": "discount:list"},
            ],
            [
                {"text": "Проверить цены", "callback_data": "discount:check"},
                {"text": "Главное меню", "callback_data": "main:home"},
            ],
        ],
    }


def list_screen(store: DiscountRadarStore, user_id: int) -> dict:
    products = store.list_products(user_id)
    buttons = _product_delete_buttons(products)
    buttons.extend(
        [
            [{"text": "Добавить товар", "callback_data": "discount:add"}],
            [{"text": "К Дисконт Радар", "callback_data": "discount:home"}],
            [{"text": "Главное меню", "callback_data": "main:home"}],
        ]
    )
    return {"text": format_product_list(products), "buttons": buttons}


def check_screen(store: DiscountRadarStore, user_id: int) -> dict:
    products = store.list_products(user_id)
    return {
        "text": format_check_screen(products),
        "buttons": [
            [{"text": "Мои товары", "callback_data": "discount:list"}],
            [{"text": "К Дисконт Радар", "callback_data": "discount:home"}],
            [{"text": "Главное меню", "callback_data": "main:home"}],
        ],
    }


def delete_product_screen(store: DiscountRadarStore, user_id: int, product_id: str) -> dict:
    deleted = store.delete_product(user_id=user_id, product_id=product_id)
    prefix = "Товар удалён." if deleted else "Не нашёл активный товар для удаления."
    screen = list_screen(store, user_id)
    screen["text"] = f"{prefix}\n\n{screen['text']}"
    return screen


def add_product_from_input(
    store: DiscountRadarStore,
    *,
    user_id: int,
    url: str,
    reference_price: int,
) -> Product:
    return store.add_product(
        user_id=user_id,
        url=url,
        reference_price=reference_price,
    )


def _product_delete_buttons(products: list[Product]) -> list[list[dict[str, str]]]:
    return [
        [
            {
                "text": f"Удалить: {product_button_label(product)}",
                "callback_data": f"discount:delete:{product.id}",
            }
        ]
        for product in products[:10]
    ]
