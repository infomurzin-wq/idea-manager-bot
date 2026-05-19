from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from idea_manager_bot.bond_radar_bridge import BondRadarBridge
from idea_manager_bot.bot import IdeaManagerApp, MENU_BONDS
from idea_manager_bot.config import Settings


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
            self.assertIn("Полипласт П02-БО-99", screen["text"])
            self.assertTrue(any(callback.startswith("bond:show:") for callback in callbacks))
            self.assertIn("bond:list:new", callbacks)

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


def make_settings() -> Settings:
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
    )


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
