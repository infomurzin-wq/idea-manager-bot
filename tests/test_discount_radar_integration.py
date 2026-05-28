from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from telegram import InlineKeyboardButton

from idea_manager_bot.bot import IdeaManagerApp, MENU_BONDS, MENU_CANCEL, MENU_DISCOUNT, MENU_PROJECTS
from idea_manager_bot.config import Settings
from idea_manager_bot.discount_radar.actions import is_ozon_url, parse_price
from idea_manager_bot.discount_radar.store import DiscountRadarStore
from idea_manager_bot.discount_radar_bridge import DiscountRadarBridge


class DiscountRadarIntegrationTest(unittest.TestCase):
    def test_bridge_renders_home_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bridge = DiscountRadarBridge(Path(tmp_dir) / "discount-radar" / "products.json")

            screen = bridge.handle_action("discount:home", user_id=100)
            callbacks = [
                item["callback_data"]
                for row in screen["buttons"]
                for item in row
            ]

            self.assertIn("Дисконт Радар", screen["text"])
            self.assertIn("discount:add", callbacks)
            self.assertIn("discount:list", callbacks)
            self.assertIn("discount:check", callbacks)

    def test_store_adds_and_lists_user_products(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = DiscountRadarStore(Path(tmp_dir) / "products.json")

            product = store.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/test",
                reference_price=1490,
            )

            products = store.list_products(100)
            self.assertEqual(product.id, products[0].id)
            self.assertEqual(1490, products[0].reference_price)
            self.assertEqual([], store.list_products(200))

    def test_bridge_adds_and_deletes_product(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bridge = DiscountRadarBridge(Path(tmp_dir) / "products.json")

            add_screen = bridge.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/test",
                reference_price=1490,
            )
            products = bridge.store.list_products(100)
            delete_screen = bridge.handle_action(
                f"discount:delete:{products[0].id}",
                user_id=100,
            )

            self.assertIn("Товар добавлен", add_screen["text"])
            self.assertIn("Товар удалён", delete_screen["text"])
            self.assertEqual([], bridge.store.list_products(100))

    def test_list_screen_shows_product_and_delete_button(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bridge = DiscountRadarBridge(Path(tmp_dir) / "products.json")
            bridge.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/test",
                reference_price=1490,
            )

            screen = bridge.handle_action("discount:list", user_id=100)
            callbacks = [
                item["callback_data"]
                for row in screen["buttons"]
                for item in row
            ]

            self.assertIn("Мои товары", screen["text"])
            self.assertIn("1 490 ₽", screen["text"])
            self.assertTrue(any(callback.startswith("discount:delete:") for callback in callbacks))

    def test_main_menu_contains_discount_radar(self) -> None:
        app = IdeaManagerApp(test_settings())

        labels = [
            button.text
            for row in app._main_menu().keyboard
            for button in row
        ]

        self.assertIn(MENU_DISCOUNT, labels)
        self.assertNotIn(MENU_PROJECTS, labels)
        self.assertNotIn(MENU_CANCEL, labels)

    def test_main_menu_places_discount_radar_next_to_bonds(self) -> None:
        app = IdeaManagerApp(test_settings())

        rows = [[button.text for button in row] for row in app._main_menu().keyboard]

        self.assertIn([MENU_BONDS, MENU_DISCOUNT], rows)

    def test_idea_and_context_action_cards_have_main_menu_exit(self) -> None:
        idea_callbacks = [
            button.callback_data
            for row in IdeaManagerApp._idea_actions("idea-1", "learning-programming").inline_keyboard
            for button in row
        ]
        context_callbacks = [
            button.callback_data
            for row in IdeaManagerApp._context_actions("ctx-1", "learning-programming").inline_keyboard
            for button in row
        ]

        self.assertIn("main:home", idea_callbacks)
        self.assertIn("main:home", context_callbacks)

    def test_list_keyboards_have_main_menu_exit(self) -> None:
        keyboard = IdeaManagerApp._with_main_menu_exit(
            [[InlineKeyboardButton("Item", callback_data="show_idea:item")]]
        )

        self.assertEqual("🏠 Главное меню", keyboard[-1][0].text)
        self.assertEqual("main:home", keyboard[-1][0].callback_data)

    def test_project_selector_can_include_main_menu_exit(self) -> None:
        app = IdeaManagerApp(test_settings())

        keyboard = app._project_selector(
            "list_ideas",
            include_all=True,
            include_main_menu=True,
        )
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]

        self.assertIn("list_ideas:__all__", callbacks)
        self.assertIn("main:home", callbacks)

    def test_main_menu_is_one_time_keyboard(self) -> None:
        app = IdeaManagerApp(test_settings())

        menu = app._main_menu()

        self.assertTrue(menu.one_time_keyboard)
        self.assertFalse(menu.is_persistent)

    def test_store_migrates_old_target_price_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "products.json"
            path.write_text(
                """
                {
                  "products": [
                    {
                      "id": "old-item",
                      "user_id": 100,
                      "url": "https://www.ozon.ru/product/test",
                      "target_price": 1490,
                      "title": null,
                      "last_price": null,
                      "last_checked_at": null,
                      "last_error": null,
                      "is_active": true,
                      "created_at": "2026-05-28T10:00:00+00:00",
                      "updated_at": "2026-05-28T10:00:00+00:00"
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            store = DiscountRadarStore(path)

            products = store.list_products(100)

            self.assertEqual(1490, products[0].reference_price)

    def test_parses_price_and_validates_ozon_url(self) -> None:
        self.assertEqual(1490, parse_price("1 490 ₽"))
        self.assertTrue(is_ozon_url("https://www.ozon.ru/product/test"))
        self.assertFalse(is_ozon_url("https://example.com/product/test"))


def test_settings() -> Settings:
    root = Path(tempfile.mkdtemp())
    return Settings(
        telegram_bot_token="test-token",
        openai_api_key=None,
        openai_model="gpt-5-mini",
        workspace_root=root,
        bot_data_dir=root / "data",
        sync_export_mode="disabled",
        sync_export_dir=None,
        github_sync_repo=None,
        github_sync_branch="main",
        github_sync_token=None,
        github_sync_base_path="",
        t_invest_token=None,
        t_invest_account_id=None,
    )


if __name__ == "__main__":
    unittest.main()
