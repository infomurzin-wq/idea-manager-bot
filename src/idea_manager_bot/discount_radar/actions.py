from __future__ import annotations

from urllib.parse import urlparse

from idea_manager_bot.discount_radar.formatter import (
    format_check_screen,
    format_home_screen,
    format_product_detail,
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
                {"text": "➕ Добавить товар", "callback_data": "discount:add"},
                {"text": "📦 Мои товары", "callback_data": "discount:list"},
            ],
            [
                {"text": "🔎 Проверить цены", "callback_data": "discount:check"},
                {"text": "🏠 Главное меню", "callback_data": "main:home"},
            ],
        ],
    }


def list_screen(store: DiscountRadarStore, user_id: int) -> dict:
    products = store.list_products(user_id)
    buttons = _product_open_buttons(products)
    buttons.extend(
        [
            [{"text": "➕ Добавить товар", "callback_data": "discount:add"}],
            [{"text": "🛒 К Дисконт Радар", "callback_data": "discount:home"}],
            [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
        ]
    )
    return {"text": format_product_list(products), "buttons": buttons}


def check_screen(store: DiscountRadarStore, user_id: int) -> dict:
    products = store.list_products(user_id)
    return {
        "text": format_check_screen(products),
        "buttons": [
            [{"text": "📦 Мои товары", "callback_data": "discount:list"}],
            [{"text": "🛒 К Дисконт Радар", "callback_data": "discount:home"}],
            [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
        ],
    }


def product_screen(store: DiscountRadarStore, user_id: int, product_id: str) -> dict:
    product = store.get_product(user_id=user_id, product_id=product_id)
    if not product:
        return {
            "text": "🛒 Дисконт Радар\n\nНе нашёл активный товар.",
            "buttons": [
                [{"text": "📦 Мои товары", "callback_data": "discount:list"}],
                [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
            ],
        }
    return {
        "text": format_product_detail(product),
        "buttons": [
            [{"text": "🔗 Открыть ссылку", "url": product.url}],
            [
                {"text": "✏️ Изменить цену", "callback_data": f"discount:edit-price:{product.id}"},
                {"text": "🗑 Удалить", "callback_data": f"discount:delete:{product.id}"},
            ],
            [
                {"text": "📦 К списку", "callback_data": "discount:list"},
                {"text": "🏠 Главное меню", "callback_data": "main:home"},
            ],
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


def update_reference_price_screen(
    store: DiscountRadarStore,
    *,
    user_id: int,
    product_id: str,
    reference_price: int,
) -> dict:
    product = store.update_reference_price(
        user_id=user_id,
        product_id=product_id,
        reference_price=reference_price,
    )
    if not product:
        return {
            "text": "🛒 Дисконт Радар\n\nНе нашёл активный товар для изменения цены.",
            "buttons": [
                [{"text": "📦 Мои товары", "callback_data": "discount:list"}],
                [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
            ],
        }
    screen = product_screen(store, user_id, product.id)
    screen["text"] = f"Последняя известная цена обновлена.\n\n{screen['text']}"
    return screen


def _product_open_buttons(products: list[Product]) -> list[list[dict[str, str]]]:
    return [
        [
            {
                "text": f"📦 {product_button_label(product)}",
                "callback_data": f"discount:show:{product.id}",
            }
        ]
        for product in products[:10]
    ]
