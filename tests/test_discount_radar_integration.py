from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from telegram import InlineKeyboardButton

from idea_manager_bot.bot import (
    IdeaManagerApp,
    MENU_BONDS,
    MENU_CANCEL,
    MENU_DISCOUNT,
    MENU_PROJECTS,
    _discount_cron_dry_run_enabled,
)
from idea_manager_bot.config import Settings
from idea_manager_bot.discount_radar.actions import check_screen, is_ozon_url, parse_price
from idea_manager_bot.discount_radar.checker import run_scheduled_check_report, run_scheduled_checks
from idea_manager_bot.discount_radar.store import DiscountRadarStore
from idea_manager_bot.discount_radar_bridge import DiscountRadarBridge


@dataclass(frozen=True)
class FakeSnapshot:
    status: str
    title: str | None = None
    price: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success"


class FakeParser:
    def __init__(self, snapshots: dict[str, FakeSnapshot]) -> None:
        self.snapshots = snapshots

    def fetch(self, url: str) -> FakeSnapshot:
        return self.snapshots[url]


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
            self.assertIn("main:home", callbacks)

    def test_discount_radar_core_screens_have_main_menu_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bridge = DiscountRadarBridge(Path(tmp_dir) / "discount-radar" / "products.json")
            bridge.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/test",
                reference_price=1490,
            )
            product = bridge.store.list_products(100)[0]

            screens = [
                bridge.handle_action("discount:home", user_id=100),
                bridge.handle_action("discount:list", user_id=100),
                bridge.handle_action("discount:check", user_id=100),
                bridge.handle_action(f"discount:show:{product.id}", user_id=100),
                bridge.handle_action("discount:unknown", user_id=100),
            ]

            for screen in screens:
                callbacks = [
                    item.get("callback_data")
                    for row in screen["buttons"]
                    for item in row
                    if item.get("callback_data")
                ]
                self.assertIn("main:home", callbacks)

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

    def test_store_lists_active_user_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = DiscountRadarStore(Path(tmp_dir) / "products.json")
            product = store.add_product(
                user_id=200,
                url="https://www.ozon.ru/product/test-2",
                reference_price=2390,
            )
            store.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/test-1",
                reference_price=1490,
            )
            store.delete_product(user_id=200, product_id=product.id)

            self.assertEqual([100], store.list_user_ids())

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

    def test_list_screen_opens_product_card(self) -> None:
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
            self.assertTrue(any(callback.startswith("discount:show:") for callback in callbacks))

    def test_product_card_has_detail_actions_and_url_button(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bridge = DiscountRadarBridge(Path(tmp_dir) / "products.json")
            bridge.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/test",
                reference_price=1490,
            )
            product = bridge.store.list_products(100)[0]

            screen = bridge.handle_action(f"discount:show:{product.id}", user_id=100)
            callbacks = [
                item.get("callback_data")
                for row in screen["buttons"]
                for item in row
                if item.get("callback_data")
            ]
            urls = [
                item.get("url")
                for row in screen["buttons"]
                for item in row
                if item.get("url")
            ]

            self.assertIn("Последняя известная цена: 1 490 ₽", screen["text"])
            self.assertIn("Новая найденная цена: неизвестно", screen["text"])
            self.assertIn("Последняя проверка: не проверялся", screen["text"])
            self.assertIn(f"discount:edit-price:{product.id}", callbacks)
            self.assertIn(f"discount:delete:{product.id}", callbacks)
            self.assertIn("discount:list", callbacks)
            self.assertIn("main:home", callbacks)
            self.assertEqual(["https://www.ozon.ru/product/test"], urls)

    def test_bridge_inline_keyboard_supports_url_buttons(self) -> None:
        keyboard = DiscountRadarBridge.inline_keyboard(
            [[{"text": "Открыть", "url": "https://www.ozon.ru/product/test"}]]
        )

        button = keyboard.inline_keyboard[0][0]

        self.assertEqual("Открыть", button.text)
        self.assertEqual("https://www.ozon.ru/product/test", button.url)
        self.assertIsNone(button.callback_data)

    def test_updates_reference_price_from_product_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bridge = DiscountRadarBridge(Path(tmp_dir) / "products.json")
            bridge.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/test",
                reference_price=1490,
            )
            product = bridge.store.list_products(100)[0]

            screen = bridge.update_reference_price(
                user_id=100,
                product_id=product.id,
                reference_price=1390,
            )

            updated = bridge.store.list_products(100)[0]
            self.assertEqual(1390, updated.reference_price)
            self.assertIn("Последняя известная цена обновлена", screen["text"])
            self.assertIn("Последняя известная цена: 1 390 ₽", screen["text"])

    def test_product_card_accepts_last_checked_price_as_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bridge = DiscountRadarBridge(Path(tmp_dir) / "products.json")
            bridge.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/test",
                reference_price=1490,
            )
            product = bridge.store.list_products(100)[0]
            bridge.store.update_check_result(
                user_id=100,
                product_id=product.id,
                price=1400,
                error=None,
                title="Кофе в зернах",
            )

            card = bridge.handle_action(f"discount:show:{product.id}", user_id=100)
            callbacks = [
                item.get("callback_data")
                for row in card["buttons"]
                for item in row
                if item.get("callback_data")
            ]
            screen = bridge.handle_action(f"discount:accept-price:{product.id}", user_id=100)
            updated = bridge.store.list_products(100)[0]

            self.assertIn(f"discount:accept-price:{product.id}", callbacks)
            self.assertEqual(1400, updated.reference_price)
            self.assertEqual(1400, updated.last_price)
            self.assertIn("Последняя известная цена обновлена до 1 400 ₽", screen["text"])
            self.assertIn("Последняя известная цена: 1 400 ₽", screen["text"])

    def test_product_card_does_not_offer_accept_price_without_successful_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bridge = DiscountRadarBridge(Path(tmp_dir) / "products.json")
            bridge.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/test",
                reference_price=1490,
            )
            product = bridge.store.list_products(100)[0]

            screen = bridge.handle_action(f"discount:show:{product.id}", user_id=100)
            callbacks = [
                item.get("callback_data")
                for row in screen["buttons"]
                for item in row
                if item.get("callback_data")
            ]

            self.assertNotIn(f"discount:accept-price:{product.id}", callbacks)

    def test_check_screen_fetches_prices_and_updates_products(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = DiscountRadarStore(Path(tmp_dir) / "products.json")
            cheaper = store.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/coffee",
                reference_price=1490,
            )
            failed = store.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/filter",
                reference_price=2390,
            )
            parser = FakeParser(
                {
                    cheaper.url: FakeSnapshot(
                        status="success",
                        title="Кофе в зернах",
                        price=1400,
                    ),
                    failed.url: FakeSnapshot(
                        status="blocked",
                        title="Фильтр для воды",
                        error="Ozon отдал страницу проверки доступа или капчу.",
                    ),
                }
            )

            screen = check_screen(store, user_id=100, parser=parser)
            products = store.list_products(100)
            checked_cheaper = next(product for product in products if product.id == cheaper.id)
            checked_failed = next(product for product in products if product.id == failed.id)

            self.assertIn("Проверка цен завершена", screen["text"])
            self.assertIn("Сигнал на покупку", screen["text"])
            self.assertIn("было: 1 490 ₽", screen["text"])
            self.assertIn("стало: 1 400 ₽", screen["text"])
            self.assertIn("снижение: 90 ₽", screen["text"])
            self.assertIn("Кофе в зернах: подешевел на 90 ₽", screen["text"])
            self.assertIn("Фильтр для воды: ошибка", screen["text"])
            urls = [
                item.get("url")
                for row in screen["buttons"]
                for item in row
                if item.get("url")
            ]
            self.assertEqual(["https://www.ozon.ru/product/coffee"], urls)
            self.assertEqual("Кофе в зернах", checked_cheaper.title)
            self.assertEqual(1400, checked_cheaper.last_price)
            self.assertIsNone(checked_cheaper.last_error)
            self.assertIsNotNone(checked_cheaper.last_checked_at)
            self.assertEqual("Фильтр для воды", checked_failed.title)
            self.assertIsNone(checked_failed.last_price)
            self.assertIn("капчу", checked_failed.last_error or "")
            self.assertIsNotNone(checked_failed.last_checked_at)

    def test_scheduled_checks_notify_only_users_with_discounts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = DiscountRadarStore(Path(tmp_dir) / "products.json")
            discounted = store.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/coffee",
                reference_price=1490,
            )
            unchanged = store.add_product(
                user_id=200,
                url="https://www.ozon.ru/product/filter",
                reference_price=2390,
            )
            parser = FakeParser(
                {
                    discounted.url: FakeSnapshot(
                        status="success",
                        title="Кофе в зернах",
                        price=1400,
                    ),
                    unchanged.url: FakeSnapshot(
                        status="success",
                        title="Фильтр для воды",
                        price=2390,
                    ),
                }
            )

            notifications = run_scheduled_checks(store, parser=parser)

            self.assertEqual([100], [item.user_id for item in notifications])
            self.assertEqual("Кофе в зернах", notifications[0].products[0].title)
            self.assertEqual(1400, notifications[0].products[0].last_price)

    def test_scheduled_check_report_counts_users_products_discounts_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = DiscountRadarStore(Path(tmp_dir) / "products.json")
            discounted = store.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/coffee",
                reference_price=1490,
            )
            unchanged = store.add_product(
                user_id=100,
                url="https://www.ozon.ru/product/filter",
                reference_price=2390,
            )
            failed = store.add_product(
                user_id=200,
                url="https://www.ozon.ru/product/cup",
                reference_price=790,
            )
            parser = FakeParser(
                {
                    discounted.url: FakeSnapshot(
                        status="success",
                        title="Кофе в зернах",
                        price=1400,
                    ),
                    unchanged.url: FakeSnapshot(
                        status="success",
                        title="Фильтр для воды",
                        price=2390,
                    ),
                    failed.url: FakeSnapshot(
                        status="blocked",
                        title="Кружка",
                        error="Ozon запросил капчу",
                    ),
                }
            )

            report = run_scheduled_check_report(store, parser=parser)

            self.assertEqual(2, report.users_checked)
            self.assertEqual(3, report.products_checked)
            self.assertEqual(1, report.discounted_products)
            self.assertEqual(1, report.products_with_errors)
            self.assertEqual([100], [item.user_id for item in report.notifications])

    def test_discount_cron_dry_run_can_be_enabled_by_arg_or_env(self) -> None:
        self.assertTrue(
            _discount_cron_dry_run_enabled(["idea-manager-bot", "discount-cron", "--dry-run"])
        )
        self.assertFalse(_discount_cron_dry_run_enabled(["idea-manager-bot", "discount-cron"]))

        with patch.dict("os.environ", {"DISCOUNT_CRON_DRY_RUN": "1"}):
            self.assertTrue(_discount_cron_dry_run_enabled(["idea-manager-bot", "discount-cron"]))

    def test_main_menu_contains_discount_radar(self) -> None:
        app = IdeaManagerApp(test_settings())

        labels = [
            button.text
            for row in app._main_menu().keyboard
            for button in row
        ]

        self.assertIn(MENU_DISCOUNT, labels)
        self.assertIn(MENU_PROJECTS, labels)
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
