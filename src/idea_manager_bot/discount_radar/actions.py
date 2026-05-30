from __future__ import annotations

from typing import Protocol
from urllib.parse import urlparse

from idea_manager_bot.discount_radar.formatter import (
    discounted_products,
    format_check_screen,
    format_home_screen,
    format_product_detail,
    format_product_list,
    format_price,
    product_button_label,
)
from idea_manager_bot.discount_radar.store import DiscountRadarStore, Product


class ProductSnapshot(Protocol):
    status: str
    title: str | None
    price: int | None
    error: str | None

    @property
    def ok(self) -> bool: ...


class ProductParser(Protocol):
    def fetch(self, url: str) -> ProductSnapshot: ...


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


def check_screen(
    store: DiscountRadarStore,
    user_id: int,
    parser: ProductParser | None = None,
) -> dict:
    if parser is None:
        from idea_manager_bot.discount_radar.parser_ozon import OzonParser

        parser = OzonParser()

    products = store.list_products(user_id)
    checked_products: list[Product] = []
    for product in products:
        snapshot = parser.fetch(product.url)
        if snapshot.ok:
            updated = store.update_check_result(
                user_id=user_id,
                product_id=product.id,
                price=snapshot.price,
                error=None,
                title=snapshot.title,
            )
        else:
            updated = store.update_check_result(
                user_id=user_id,
                product_id=product.id,
                price=None,
                error=snapshot.error or snapshot.status,
                title=snapshot.title,
            )
        checked_products.append(updated or product)

    return {
        "text": format_check_screen(checked_products),
        "buttons": [
            *_discount_alert_buttons(checked_products),
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


def _discount_alert_buttons(products: list[Product]) -> list[list[dict[str, str]]]:
    buttons: list[list[dict[str, str]]] = []
    for product in discounted_products(products)[:5]:
        discount = product.reference_price - (product.last_price or 0)
        label = product_button_label(product)[:30]
        buttons.append(
            [
                {
                    "text": f"🛒 Открыть: {label} (-{format_price(discount)})",
                    "url": product.url,
                }
            ]
        )
    return buttons
