from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from telegram import Chat, Message, MessageOriginChannel

from idea_manager_bot.bond_portfolio import render_portfolio_screen
from idea_manager_bot.bond_radar_bridge import BondRadarBridge
from idea_manager_bot.bot import IdeaManagerApp, MENU_BONDS
from idea_manager_bot.config import Settings
from idea_manager_bot.link_reader import LinkReader


MYCODEX_ROOT = Path(__file__).resolve().parents[2]
BOND_RADAR_PROJECT = MYCODEX_ROOT / "learning-programming" / "04_projects" / "bond-radar-bot"
BOND_RADAR_STORE = BOND_RADAR_PROJECT / "data" / "candidates_store.jsonl"


class BondRadarIntegrationTest(unittest.TestCase):
    def test_bridge_renders_home_screen_from_current_store(self) -> None:
        bridge = BondRadarBridge(
            scripts_dir=BOND_RADAR_PROJECT / "scripts",
            store_path=BOND_RADAR_STORE,
        )

        screen = bridge.handle_action("bond:home")

        self.assertIn("Облигации", screen["text"])
        self.assertIn("Новые кандидаты", screen["text"])
        self.assertEqual("bond:list:new", screen["buttons"][0][0]["callback_data"])

    def test_bridge_uses_env_project_dir_override(self) -> None:
        previous_project_dir = os.environ.get("BOND_RADAR_PROJECT_DIR")
        previous_scripts_dir = os.environ.get("BOND_RADAR_SCRIPTS_DIR")
        previous_store_path = os.environ.get("BOND_RADAR_STORE_PATH")
        try:
            os.environ["BOND_RADAR_PROJECT_DIR"] = str(BOND_RADAR_PROJECT)
            os.environ.pop("BOND_RADAR_SCRIPTS_DIR", None)
            os.environ.pop("BOND_RADAR_STORE_PATH", None)

            bridge = BondRadarBridge.from_workspace(Path("/tmp/not-the-mycodex-root"))

            self.assertEqual((BOND_RADAR_PROJECT / "scripts").resolve(), bridge.scripts_dir)
            self.assertEqual(BOND_RADAR_STORE.resolve(), bridge.store_path)
        finally:
            restore_env("BOND_RADAR_PROJECT_DIR", previous_project_dir)
            restore_env("BOND_RADAR_SCRIPTS_DIR", previous_scripts_dir)
            restore_env("BOND_RADAR_STORE_PATH", previous_store_path)

    def test_bridge_uses_explicit_scripts_and_store_overrides(self) -> None:
        previous_scripts_dir = os.environ.get("BOND_RADAR_SCRIPTS_DIR")
        previous_store_path = os.environ.get("BOND_RADAR_STORE_PATH")
        try:
            os.environ["BOND_RADAR_SCRIPTS_DIR"] = str(BOND_RADAR_PROJECT / "scripts")
            os.environ["BOND_RADAR_STORE_PATH"] = str(BOND_RADAR_STORE)

            bridge = BondRadarBridge.from_workspace(Path("/tmp/not-the-mycodex-root"))

            self.assertEqual((BOND_RADAR_PROJECT / "scripts").resolve(), bridge.scripts_dir)
            self.assertEqual(BOND_RADAR_STORE.resolve(), bridge.store_path)
        finally:
            restore_env("BOND_RADAR_SCRIPTS_DIR", previous_scripts_dir)
            restore_env("BOND_RADAR_STORE_PATH", previous_store_path)

    def test_bridge_falls_back_to_bundled_scripts_for_deploy_context(self) -> None:
        previous_project_dir = os.environ.get("BOND_RADAR_PROJECT_DIR")
        previous_scripts_dir = os.environ.get("BOND_RADAR_SCRIPTS_DIR")
        previous_store_path = os.environ.get("BOND_RADAR_STORE_PATH")
        previous_bot_data_dir = os.environ.get("BOT_DATA_DIR")
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                os.environ.pop("BOND_RADAR_PROJECT_DIR", None)
                os.environ.pop("BOND_RADAR_SCRIPTS_DIR", None)
                os.environ.pop("BOND_RADAR_STORE_PATH", None)
                os.environ["BOT_DATA_DIR"] = tmp_dir

                bridge = BondRadarBridge.from_workspace(Path("/tmp/not-the-mycodex-root"))

                self.assertEqual(BondRadarBridge._bundled_scripts_dir(), bridge.scripts_dir)
                self.assertEqual((Path(tmp_dir) / "bond-radar" / "candidates_store.jsonl").resolve(), bridge.store_path.resolve())
            finally:
                restore_env("BOND_RADAR_PROJECT_DIR", previous_project_dir)
                restore_env("BOND_RADAR_SCRIPTS_DIR", previous_scripts_dir)
                restore_env("BOND_RADAR_STORE_PATH", previous_store_path)
                restore_env("BOT_DATA_DIR", previous_bot_data_dir)

    def test_bridge_seeds_missing_store_from_bundled_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "bond-radar" / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )

            screen = bridge.handle_action("bond:home")

            self.assertTrue(store_path.exists())
            self.assertIn("Новые кандидаты: 25", screen["text"])
            self.assertEqual(25, len(store_path.read_text(encoding="utf-8").splitlines()))

    def test_home_screen_has_manual_add_button(self) -> None:
        bridge = BondRadarBridge(
            scripts_dir=BOND_RADAR_PROJECT / "scripts",
            store_path=BOND_RADAR_STORE,
        )

        screen = bridge.handle_action("bond:home")
        callbacks = [
            item["callback_data"]
            for row in screen["buttons"]
            for item in row
        ]

        self.assertIn("bond:add:manual", callbacks)

    def test_home_screen_has_portfolio_button(self) -> None:
        bridge = BondRadarBridge(
            scripts_dir=BondRadarBridge._bundled_scripts_dir(),
            store_path=BOND_RADAR_STORE,
        )

        screen = bridge.handle_action("bond:home")
        callbacks = [
            item["callback_data"]
            for row in screen["buttons"]
            for item in row
        ]

        self.assertIn("bond:portfolio", callbacks)

    def test_bridge_imports_manual_text_into_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            text = (
                "Полипласт П02-БО-99 (А)\n"
                "Купон: 18%\n"
                "YTM: 19,5%\n"
                "Выплаты: 12 раз в год\n"
                "Срок: 3 года\n"
                "Сбор заявок до: 25 мая\n"
                "Размещение: 28 мая 2026\n"
            )

            screen = bridge.import_manual_text(text)
            callbacks = [
                item["callback_data"]
                for row in screen["buttons"]
                for item in row
            ]

            self.assertIn("Ручной импорт завершен", screen["text"])
            self.assertIn("Новых: 1", screen["text"])
            self.assertEqual(1, screen["card_count"])
            self.assertEqual(1, screen["affected_count"])
            self.assertIn("Полипласт П02-БО-99", screen["text"])
            self.assertTrue(any(callback.startswith("bond:show:") for callback in callbacks))
            self.assertIn("bond:list:new", callbacks)

    def test_bridge_imports_manual_text_with_title_before_bullets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            text = (
                "ПР-Лизинг 002Р-03 (RU000A10CJ92)\n\n"
                "• Доходность к оферте: 25,2%\n"
                "• Купон: 20%, ежемесячно\n"
                "• ТКД: 20,6%\n"
                "• Текущая цена: 97% (970 ₽)\n"
                "• Дата погашения: 05.07.2035\n"
                "! Call-оферта: 16.08.2027\n"
                "! Put-оферта: 23.08.2027\n"
            )

            screen = bridge.import_manual_text(text)

            self.assertIn("ПР-Лизинг 002Р-03", screen["text"])
            self.assertNotIn("Доходность к оферте: 25,2% (new)", screen["text"])

    def test_bridge_imports_telegram_post_with_hashtag_header_issuer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            text = (
                "#тлк #анонс #презентацияэмитента\n"
                "Транспортная лизинговая компания / ЯрКамп Лизинг возвращается на рынок облигаций "
                "с интригующим предложением!\n\n"
                "Обобщенные параметры нового выпуска облигаций ТЛК (ruBB-):\n"
                "- 200-250 млн р.\n"
                "- 3 года до погашения, амортизация последние 1,5 года\n"
                "- оферта call через 1,5 года\n"
                "- ставка купона 26%\n"
                "- YTM 29,34% годовых\n"
                "- ориентир даты размещения 13 мая 2026 года\n"
            )

            import_screen = bridge.import_manual_text(
                text,
                source_channel="@probonds",
                source_url="https://t.me/probonds/16341",
            )
            show_callback = next(
                item["callback_data"]
                for row in import_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:show:")
            )
            detail_screen = bridge.handle_action(show_callback)

            self.assertIn("Эмитент: Транспортная лизинговая компания", detail_screen["text"])
            self.assertNotIn("Эмитент: #тлк #анонс", detail_screen["text"])
            self.assertIn("Погашение / срок: 3 года", detail_screen["text"])
            self.assertIn("Объем: 200-250 млн р", detail_screen["text"])

    def test_bridge_imports_manual_text_with_clickable_source_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            text = (
                "Полипласт П02-БО-99 (А)\n"
                "Купон: 18%\n"
                "YTM: 19,5%\n"
                "Выплаты: 12 раз в год\n"
                "Срок: 3 года\n"
                "Сбор заявок до: 25 мая\n"
            )

            import_screen = bridge.import_manual_text(
                text,
                source_channel="@test_channel",
                source_url="https://t.me/test_channel/123",
            )
            show_callback = next(
                item["callback_data"]
                for row in import_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:show:")
            )
            detail_screen = bridge.handle_action(show_callback)

            self.assertIn("Источники:", detail_screen["text"])
            self.assertIn("@test_channel", detail_screen["text"])
            self.assertIn("https://t.me/test_channel/123", detail_screen["text"])

    def test_bridge_appends_manual_text_to_existing_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            import_screen = bridge.import_manual_text(
                "Полипласт П02-БО-99 (А)\n"
                "Купон: 18%\n"
                "Выплаты: 12 раз в год\n"
                "Срок: 3 года\n"
                "Сбор заявок до: 25 мая\n"
                "Размещение: 28 мая 2026\n",
                source_channel="@first",
                source_url="https://t.me/first/1",
            )
            show_callback = next(
                item["callback_data"]
                for row in import_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:show:")
            )
            detail_screen = bridge.handle_action(show_callback)
            append_callback = next(
                item["callback_data"]
                for row in detail_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:append:")
            )

            appended_screen = bridge.append_manual_text(
                append_callback,
                "Полипласт П02-БО-99 (А)\n"
                "Купон: 18%\n"
                "YTM: 19,4%\n"
                "Выплаты: 12 раз в год\n"
                "Срок: 3 года\n"
                "Сбор заявок до: 25 мая\n",
                source_channel="@second",
                source_url="https://t.me/second/2",
            )

            self.assertIn("Данные карточки дополнены.", appended_screen["text"])
            self.assertIn("YTM: 19.4%", appended_screen["text"])
            self.assertIn("Рейтинг: A", appended_screen["text"])
            self.assertIn("Источников: 2", appended_screen["text"])

    def test_bridge_renders_separate_isin_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            import_screen = bridge.import_manual_text(
                "ПР-Лизинг 002Р-03 (RU000A10CJ92)\n"
                "Купон: 20%, ежемесячно\n"
                "YTM: 25,2%\n",
            )
            show_callback = next(
                item["callback_data"]
                for row in import_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:show:")
            )
            detail_screen = bridge.handle_action(show_callback)
            isin_callback = next(
                item["callback_data"]
                for row in detail_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:isin:")
            )

            isin_screen = bridge.handle_action(isin_callback)

            self.assertEqual("RU000A10CJ92", isin_screen["text"])

    def test_bridge_opens_edit_menu_from_append_button(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            import_screen = bridge.import_manual_text(
                "ПР-Лизинг 002Р-03 (RU000A10CJ92)\n"
                "Купон: 20%, ежемесячно\n"
                "YTM: 25,2%\n",
            )
            show_callback = next(
                item["callback_data"]
                for row in import_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:show:")
            )
            detail_screen = bridge.handle_action(show_callback)
            edit_callback = next(
                item["callback_data"]
                for row in detail_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:append:")
            )

            edit_screen = bridge.handle_action(edit_callback)

            self.assertIn("Редактировать карточку: ПР-Лизинг 002Р-03", edit_screen["text"])
            callbacks = [
                item["callback_data"]
                for row in edit_screen["buttons"]
                for item in row
            ]
            self.assertTrue(any(callback.startswith("bond:edit:") for callback in callbacks))
            self.assertTrue(any(callback.startswith("bond:append-text:") for callback in callbacks))

    def test_bridge_edits_manual_card_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            import_screen = bridge.import_manual_text(
                "ПР-Лизинг 002Р-03 (RU000A10CJ92)\n"
                "Купон: 20%, ежемесячно\n"
                "YTM: 25,2%\n",
            )
            show_callback = next(
                item["callback_data"]
                for row in import_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:show:")
            )
            detail_screen = bridge.handle_action(show_callback)
            edit_callback = next(
                item["callback_data"]
                for row in detail_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:append:")
            )
            edit_screen = bridge.handle_action(edit_callback)
            ytm_callback = next(
                item["callback_data"]
                for row in edit_screen["buttons"]
                for item in row
                if item["text"] == "YTM"
            )

            updated_screen = bridge.edit_manual_field(ytm_callback, "19.4%")

            self.assertIn("Поле обновлено: YTM.", updated_screen["text"])
            self.assertIn("YTM: 19.4%", updated_screen["text"])

    def test_bridge_research_question_uses_card_context_and_stores_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            import_screen = bridge.import_manual_text(
                "ПР-Лизинг 002Р-03 (RU000A10CJ92)\n"
                "Купон: 20%, ежемесячно\n"
                "YTM: 25,2%\n",
            )
            show_callback = next(
                item["callback_data"]
                for row in import_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:show:")
            )
            detail_screen = bridge.handle_action(show_callback)
            research_callback = next(
                item["callback_data"]
                for row in detail_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:research:")
            )
            llm = FakeBondResearchLLM()

            research_screen = bridge.research_question(
                research_callback,
                "Какие риски проверить?",
                llm,
            )

            self.assertIn("Research: ПР-Лизинг 002Р-03", research_screen["text"])
            self.assertIn("Ответ fake research", research_screen["text"])
            self.assertIn("Всего вопросов: 1", research_screen["text"])
            self.assertIn("ПР-Лизинг 002Р-03", llm.card_context)
            telegram_actions = bridge._import_from_scripts_dir("telegram_actions")
            candidate_store = bridge._import_from_scripts_dir("candidate_store")
            records = candidate_store.load_store(store_path)
            key = telegram_actions.resolve_action_key(
                records,
                research_callback.split(":")[-1],
            )
            record = candidate_store.get_candidate(records, key)
            self.assertEqual("Какие риски проверить?", record["research"][0]["question"])
            self.assertEqual("Ответ fake research", record["research"][0]["answer"])

    def test_bridge_renders_research_history_from_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            import_screen = bridge.import_manual_text(
                "ПР-Лизинг 002Р-03 (RU000A10CJ92)\n"
                "Купон: 20%, ежемесячно\n"
                "YTM: 25,2%\n",
            )
            show_callback = next(
                item["callback_data"]
                for row in import_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:show:")
            )
            detail_screen = bridge.handle_action(show_callback)
            research_callback = next(
                item["callback_data"]
                for row in detail_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:research:")
            )
            bridge.research_question(research_callback, "Что проверить?", FakeBondResearchLLM())
            history_callback = next(
                item["callback_data"]
                for row in detail_screen["buttons"]
                for item in row
                if item["callback_data"].startswith("bond:research-history:")
            )

            history_screen = bridge.handle_action(history_callback)

            self.assertIn("История research: ПР-Лизинг 002Р-03", history_screen["text"])
            self.assertIn("Что проверить?", history_screen["text"])
            self.assertIn("Ответ fake research", history_screen["text"])
            self.assertTrue(
                any(
                    item["callback_data"].startswith("bond:research:")
                    for row in history_screen["buttons"]
                    for item in row
                )
            )

    def test_portfolio_screen_sorts_positions_by_sum(self) -> None:
        snapshot = {
            "fetched_at": "2026-05-21T12:00:00+00:00",
            "account_id": "account-1",
            "positions": [
                {"name": "Small Bond", "isin": "RU1", "quantity": 1, "position_sum": 100.0, "expected_yield": 5.0, "maturity_date": "2028-01-01", "currency": "rub"},
                {"name": "Large Bond", "isin": "RU2", "quantity": 2, "position_sum": 500.0, "expected_yield": 10.0, "maturity_date": "2027-01-01", "currency": "rub"},
            ],
        }

        screen = render_portfolio_screen(snapshot, sort="sum_desc")

        self.assertIn("Портфель облигаций", screen["text"])
        self.assertLess(screen["text"].index("Large Bond"), screen["text"].index("Small Bond"))
        callbacks = [item["callback_data"] for row in screen["buttons"] for item in row]
        self.assertIn("bond:portfolio:maturity_asc", callbacks)
        self.assertIn("bond:portfolio:sum_asc", callbacks)

    def test_build_portfolio_screen_refreshes_snapshot_each_time(self) -> None:
        app = IdeaManagerApp(make_settings(t_invest_token="token", t_invest_account_id="account-1"))
        app.t_invest = FakeTInvestClient()

        screen = app._build_bond_portfolio_screen("bond:portfolio:yield_desc")

        self.assertEqual(1, app.t_invest.calls)
        self.assertIn("Портфель облигаций", screen["text"])
        self.assertIn("Demo Bond", screen["text"])
        self.assertTrue((app.settings.bot_data_dir / "bond-radar" / "portfolio_snapshot.json").exists())

    def test_build_portfolio_screen_requires_t_invest_token(self) -> None:
        app = IdeaManagerApp(make_settings(t_invest_token=None))

        screen = app._build_bond_portfolio_screen("bond:portfolio")

        self.assertIn("T_INVEST_TOKEN не настроен", screen["text"])

    def test_bond_manual_import_source_channel_uses_telegram_channel_from_url(self) -> None:
        self.assertEqual(
            "@probonds",
            IdeaManagerApp._bond_manual_source_channel("https://t.me/probonds/123"),
        )

    def test_bond_manual_import_source_channel_handles_telegram_web_post_url(self) -> None:
        self.assertEqual(
            "@probonds",
            IdeaManagerApp._bond_manual_source_channel("https://t.me/s/probonds/123"),
        )

    def test_bond_manual_import_source_channel_uses_web_host_for_regular_urls(self) -> None:
        self.assertEqual(
            "web:smart-lab.ru",
            IdeaManagerApp._bond_manual_source_channel("https://smart-lab.ru/bonds/"),
        )

    def test_bond_manual_import_prefers_telegram_post_url_over_regular_url(self) -> None:
        payload = {
            "telegram_source_url": "https://t.me/probonds/123",
            "source_url": "https://ivolgacap.ru/placement",
        }

        self.assertEqual("https://t.me/probonds/123", IdeaManagerApp._bond_manual_source_url(payload))

    def test_first_telegram_post_url_ignores_plain_channel_links(self) -> None:
        self.assertEqual(
            "https://t.me/probonds/123",
            IdeaManagerApp._first_telegram_post_url(
                [
                    "https://ivolgacap.ru/placement",
                    "https://t.me/probonds",
                    "https://t.me/probonds/123",
                ]
            ),
        )

    def test_first_telegram_post_url_accepts_web_post_links(self) -> None:
        self.assertEqual(
            "https://t.me/s/probonds/123",
            IdeaManagerApp._first_telegram_post_url(["https://t.me/s/probonds/123"]),
        )

    def test_telegram_forward_source_builds_public_channel_post_url(self) -> None:
        message = Message(
            message_id=1000,
            date=datetime(2026, 5, 21, tzinfo=UTC),
            chat=Chat(id=1, type="private"),
            forward_origin=MessageOriginChannel(
                date=datetime(2026, 5, 21, tzinfo=UTC),
                chat=Chat(id=-100123, type="channel", title="Pro Bonds", username="probonds"),
                message_id=123,
            ),
        )

        channel, url = IdeaManagerApp._telegram_forward_source(message)

        self.assertEqual("@probonds", channel)
        self.assertEqual("https://t.me/probonds/123", url)

    def test_bond_manual_import_text_includes_fetched_page_content(self) -> None:
        text = IdeaManagerApp._build_bond_manual_import_text(
            {
                "normalized_text": "https://example.com/post",
                "raw_input": "https://example.com/post",
                "extracted_content": "Полипласт П02-БО-99\nКупон: 18%",
            }
        )

        self.assertIn("https://example.com/post", text)
        self.assertIn("Полипласт П02-БО-99", text)

    def test_bond_manual_import_diagnostics_are_added_only_for_empty_link_imports(self) -> None:
        screen = {"text": "Ручной импорт завершен.\nНайдено карточек: 0", "card_count": 0}
        payload = {
            "source_url": "https://t.me/probonds/16341",
            "link_fetch_status": "success",
            "extracted_content": "Текст без купона и YTM",
            "link_fetch_error": None,
        }

        IdeaManagerApp._add_bond_import_diagnostics(screen, payload, "https://t.me/probonds/16341\n\nТекст без купона и YTM")

        self.assertIn("Диагностика ссылки:", screen["text"])
        self.assertIn("- чтение ссылки: success", screen["text"])
        self.assertIn("- извлечено текста:", screen["text"])
        self.assertIn("Фрагмент, который ушёл в парсер:", screen["text"])

    def test_bond_manual_import_diagnostics_are_skipped_for_successful_imports(self) -> None:
        screen = {"text": "Ручной импорт завершен.\nНайдено карточек: 1", "card_count": 1}

        IdeaManagerApp._add_bond_import_diagnostics(
            screen,
            {"source_url": "https://t.me/probonds/16341", "link_fetch_status": "success"},
            "Купон 20%",
        )

        self.assertNotIn("Диагностика ссылки:", screen["text"])

    def test_link_reader_extracts_public_telegram_post_text(self) -> None:
        html = """
        <html><body>
          <div class="tgme_widget_message_text js-message_text" dir="auto">
            ПР-Лизинг 002Р-03 (RU000A10CJ92)<br/>
            Купон: 20%, ежемесячно<br/>
            YTM: 25,2%
          </div>
          <div class="tgme_widget_message_footer">Open in Telegram</div>
        </body></html>
        """

        text = LinkReader._extract_telegram_post_text(html)

        self.assertIn("ПР-Лизинг 002Р-03 (RU000A10CJ92)", text)
        self.assertIn("Купон: 20%, ежемесячно", text)
        self.assertIn("YTM: 25,2%", text)
        self.assertNotIn("Open in Telegram", text)

    def test_link_reader_prefers_telegram_embed_url_for_post_links(self) -> None:
        self.assertEqual(
            [
                "https://t.me/probonds/16341?embed=1&mode=tme",
                "https://t.me/probonds/16341",
            ],
            LinkReader._candidate_urls("https://t.me/probonds/16341"),
        )

    def test_link_reader_rewrites_telegram_web_post_link_to_embed_url(self) -> None:
        self.assertEqual(
            "https://t.me/probonds/16341?embed=1&mode=tme",
            LinkReader._telegram_embed_url("https://t.me/s/probonds/16341"),
        )

    def test_reject_from_watchlist_keeps_back_navigation_to_watchlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            bridge.handle_action("bond:home")

            telegram_actions = bridge._import_from_scripts_dir("telegram_actions")
            candidate_store = bridge._import_from_scripts_dir("candidate_store")
            records = candidate_store.load_store(store_path)
            key = next(
                key
                for key, record in records.items()
                if record["storage"]["status"] == "new"
            )
            short_id = telegram_actions.short_callback_id(key)

            bridge.handle_action(f"bond:watch:{short_id}")
            watchlist_screen = bridge.handle_action("bond:list:watchlist")
            show_callback = watchlist_screen["buttons"][1][0]["callback_data"]
            self.assertEqual(f"bond:show:watchlist:{short_id}", show_callback)

            detail_screen = bridge.handle_action(show_callback)
            reject_callback = detail_screen["buttons"][0][0]["callback_data"]
            self.assertEqual(f"bond:reject:watchlist:{short_id}", reject_callback)

            rejected_screen = bridge.handle_action(reject_callback)

            self.assertIn("Статус: отклонен", rejected_screen["text"])
            self.assertIn({"text": "Назад", "callback_data": "bond:list:watchlist"}, rejected_screen["buttons"][-1])

    def test_delete_rejected_candidate_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            bridge.handle_action("bond:home")

            telegram_actions = bridge._import_from_scripts_dir("telegram_actions")
            candidate_store = bridge._import_from_scripts_dir("candidate_store")
            records = candidate_store.load_store(store_path)
            key = next(
                key
                for key, record in records.items()
                if record["storage"]["status"] == "new"
            )
            short_id = telegram_actions.short_callback_id(key)

            bridge.handle_action(f"bond:reject:{short_id}")
            confirm_screen = bridge.handle_action(f"bond:delete:rejected:{short_id}")
            self.assertIn("Удалить карточку:", confirm_screen["text"])
            self.assertIn(
                {"text": "Удалить навсегда", "callback_data": f"bond:delete-confirm:rejected:{short_id}"},
                confirm_screen["buttons"][0],
            )

            deleted_screen = bridge.handle_action(f"bond:delete-confirm:rejected:{short_id}")
            records = candidate_store.load_store(store_path)

            self.assertIn("Карточка удалена:", deleted_screen["text"])
            self.assertEqual(24, len(records))

    def test_list_pagination_keeps_card_back_navigation_to_same_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            bridge.handle_action("bond:home")

            page_screen = bridge.handle_action("bond:list:new:2")
            show_callback = page_screen["buttons"][2][0]["callback_data"]

            self.assertIn("Страница 2/3", page_screen["text"])
            self.assertIn("Показано 11-20 из 25.", page_screen["text"])
            self.assertTrue(show_callback.startswith("bond:show:new~2:"))

            detail_screen = bridge.handle_action(show_callback)

            self.assertIn({"text": "Назад", "callback_data": "bond:list:new:2"}, detail_screen["buttons"][-1])

    def test_sort_controls_exist_for_rejected_list_and_keep_back_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_path = Path(tmp_dir) / "candidates_store.jsonl"
            bridge = BondRadarBridge(
                scripts_dir=BondRadarBridge._bundled_scripts_dir(),
                store_path=store_path,
            )
            bridge.handle_action("bond:home")

            sorted_screen = bridge.handle_action("bond:list:rejected:1:ytm_desc")

            self.assertIn({"text": "Доходность ↓", "callback_data": "bond:list:rejected:1:ytm_asc"}, sorted_screen["buttons"][0])
            self.assertIn({"text": "Погашение ↑↓", "callback_data": "bond:list:rejected:1:maturity_desc"}, sorted_screen["buttons"][0])
            self.assertIn({"text": "Рейтинг ↑↓", "callback_data": "bond:list:rejected:1:rating_desc"}, sorted_screen["buttons"][0])

    def test_bridge_builds_inline_keyboard(self) -> None:
        markup = BondRadarBridge.inline_keyboard(
            [[{"text": "Новые кандидаты", "callback_data": "bond:list:new"}]]
        )

        self.assertEqual("Новые кандидаты", markup.inline_keyboard[0][0].text)
        self.assertEqual("bond:list:new", markup.inline_keyboard[0][0].callback_data)

    def test_bridge_unavailable_screen_has_main_menu_button(self) -> None:
        bridge = BondRadarBridge(
            scripts_dir=Path("/definitely/missing/bond-radar/scripts"),
            store_path=Path("/definitely/missing/candidates.jsonl"),
        )

        screen = bridge.handle_action("bond:home")

        self.assertIn("Bond Radar scripts не найдены", screen["text"])
        self.assertEqual("main:home", screen["buttons"][0][0]["callback_data"])

    def test_main_menu_contains_bonds_entry(self) -> None:
        app = IdeaManagerApp(make_settings())

        labels = [
            button.text
            for row in app._main_menu().keyboard
            for button in row
        ]

        self.assertIn(MENU_BONDS, labels)


def make_settings(t_invest_token: str | None = None, t_invest_account_id: str | None = None) -> Settings:
    temp_root = Path(tempfile.mkdtemp(prefix="idea-manager-bot-test-workspace-"))
    data_dir = Path(tempfile.mkdtemp(prefix="idea-manager-bot-test-data-"))
    os.environ.setdefault("BOND_RADAR_PROJECT_DIR", str(BOND_RADAR_PROJECT))
    return Settings(
        telegram_bot_token="test-token",
        openai_api_key=None,
        openai_model="gpt-5-mini",
        workspace_root=temp_root,
        bot_data_dir=data_dir,
        sync_export_mode="disabled",
        sync_export_dir=None,
        github_sync_repo=None,
        github_sync_branch="main",
        github_sync_token=None,
        github_sync_base_path="",
        t_invest_token=t_invest_token,
        t_invest_account_id=t_invest_account_id,
    )


class FakeBondResearchLLM:
    def __init__(self) -> None:
        self.card_context = ""

    def research_bond(self, question: str, card_context: str, history: list[dict]) -> str:
        self.card_context = card_context
        self.question = question
        self.history = history
        return "Ответ fake research"


class FakeTInvestClient:
    configured = True

    def __init__(self) -> None:
        self.calls = 0

    def fetch_portfolio_snapshot(self, account_id: str | None = None) -> Any:
        self.calls += 1
        return type(
            "Snapshot",
            (),
            {
                "fetched_at": "2026-05-21T12:00:00+00:00",
                "account_id": account_id or "account-1",
                "positions": [
                    {
                        "name": "Demo Bond",
                        "isin": "RU0000000001",
                        "quantity": 1,
                        "position_sum": 100.0,
                        "expected_yield": 5.0,
                        "maturity_date": "2027-01-01",
                        "currency": "rub",
                    }
                ],
            },
        )()


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
