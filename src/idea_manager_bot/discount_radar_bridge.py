from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from idea_manager_bot.discount_radar import actions
from idea_manager_bot.discount_radar.store import DiscountRadarStore


@dataclass(frozen=True)
class DiscountRadarBridge:
    store_path: Path

    @classmethod
    def from_data_dir(cls, bot_data_dir: Path) -> "DiscountRadarBridge":
        return cls(store_path=bot_data_dir / "discount-radar" / "products.json")

    @property
    def store(self) -> DiscountRadarStore:
        return DiscountRadarStore(self.store_path)

    def handle_action(self, action: str, *, user_id: int) -> dict[str, Any]:
        if action == "discount:home":
            return actions.home_screen(self.store, user_id)
        if action == "discount:list":
            return actions.list_screen(self.store, user_id)
        if action == "discount:check":
            return actions.check_screen(self.store, user_id)
        if action.startswith("discount:show:"):
            product_id = action.removeprefix("discount:show:")
            return actions.product_screen(self.store, user_id, product_id)
        if action.startswith("discount:delete:"):
            product_id = action.removeprefix("discount:delete:")
            return actions.delete_product_screen(self.store, user_id, product_id)
        return {
            "text": "🛒 Дисконт Радар\n\nНеизвестное действие.",
            "buttons": [[{"text": "🛒 К Дисконт Радар", "callback_data": "discount:home"}]],
        }

    def add_product(self, *, user_id: int, url: str, reference_price: int) -> dict[str, Any]:
        product = actions.add_product_from_input(
            self.store,
            user_id=user_id,
            url=url,
            reference_price=reference_price,
        )
        return {
            "text": (
                "🛒 Товар добавлен в Дисконт Радар.\n\n"
                f"ID: {product.id}\n"
                f"Последняя цена: {reference_price} ₽\n\n"
                "Буду сигналить, если новая цена станет ниже этой суммы. "
                "Даже небольшое снижение считаем поводом для уведомления.\n\n"
                "Реальное чтение цены Ozon подключим отдельным этапом."
            ),
            "buttons": [
                [{"text": "📦 Мои товары", "callback_data": "discount:list"}],
                [{"text": "🛒 К Дисконт Радар", "callback_data": "discount:home"}],
                [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
            ],
        }

    def update_reference_price(
        self,
        *,
        user_id: int,
        product_id: str,
        reference_price: int,
    ) -> dict[str, Any]:
        return actions.update_reference_price_screen(
            self.store,
            user_id=user_id,
            product_id=product_id,
            reference_price=reference_price,
        )

    @staticmethod
    def parse_price(value: str) -> int | None:
        return actions.parse_price(value)

    @staticmethod
    def is_ozon_url(value: str) -> bool:
        return actions.is_ozon_url(value)

    @staticmethod
    def inline_keyboard(button_rows: list[list[dict[str, str]]]) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton(
                    item["text"],
                    url=item.get("url"),
                    callback_data=item.get("callback_data"),
                )
                for item in row
            ]
            for row in button_rows
        ]
        return InlineKeyboardMarkup(keyboard)
