from __future__ import annotations

import importlib
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


@dataclass(frozen=True)
class BondRadarBridge:
    scripts_dir: Path
    store_path: Path

    @classmethod
    def from_workspace(cls, workspace_root: Path) -> "BondRadarBridge":
        project_dir = cls._configured_project_dir(workspace_root)
        scripts_dir = cls._configured_scripts_dir(project_dir)
        store_path = cls._configured_store_path(project_dir)
        return cls(scripts_dir=scripts_dir, store_path=store_path)

    @staticmethod
    def _configured_project_dir(workspace_root: Path) -> Path:
        raw_project_dir = os.getenv("BOND_RADAR_PROJECT_DIR", "").strip()
        if raw_project_dir:
            return Path(raw_project_dir).expanduser().resolve()
        return workspace_root / "learning-programming" / "04_projects" / "bond-radar-bot"

    @classmethod
    def _configured_scripts_dir(cls, project_dir: Path) -> Path:
        raw_scripts_dir = os.getenv("BOND_RADAR_SCRIPTS_DIR", "").strip()
        if raw_scripts_dir:
            return Path(raw_scripts_dir).expanduser().resolve()
        external_scripts_dir = project_dir / "scripts"
        if external_scripts_dir.exists():
            return external_scripts_dir.resolve()
        return cls._bundled_scripts_dir()

    @classmethod
    def _configured_store_path(cls, project_dir: Path) -> Path:
        raw_store_path = os.getenv("BOND_RADAR_STORE_PATH", "").strip()
        if raw_store_path:
            return Path(raw_store_path).expanduser().resolve()
        external_store_path = project_dir / "data" / "candidates_store.jsonl"
        if project_dir.exists():
            return external_store_path.resolve()
        bot_data_dir = Path(os.getenv("BOT_DATA_DIR", "data")).expanduser().resolve()
        return bot_data_dir / "bond-radar" / "candidates_store.jsonl"

    @staticmethod
    def _bundled_scripts_dir() -> Path:
        return Path(__file__).resolve().parent / "bond_radar_scripts"

    @staticmethod
    def _bundled_seed_store_path() -> Path:
        return Path(__file__).resolve().parent / "bond_radar_seed" / "candidates_store.jsonl"

    def handle_action(self, action: str) -> dict[str, Any]:
        if not self.scripts_dir.exists():
            return self._unavailable_screen(
                "Bond Radar scripts не найдены. Проверь WORKSPACE_ROOT или BOND_RADAR_STORE_PATH."
            )

        try:
            self._ensure_store_exists()
            telegram_actions = self._import_from_scripts_dir("telegram_actions")
            return telegram_actions.handle_action(action, self.store_path)
        except Exception as exc:  # noqa: BLE001
            return self._unavailable_screen(f"Bond Radar временно недоступен: {exc}")

    def import_manual_text(
        self,
        text: str,
        *,
        source_channel: str = "manual",
        source_url: str | None = None,
    ) -> dict[str, Any]:
        if not text.strip():
            return {
                "text": "Не получил текст для разбора.",
                "buttons": [[{"text": "К облигациям", "callback_data": "bond:home"}]],
            }

        try:
            self._ensure_store_exists()
            extract_candidate = self._import_from_scripts_dir("extract_candidate")
            deduplicate_candidates = self._import_from_scripts_dir("deduplicate_candidates")
            candidate_store = self._import_from_scripts_dir("candidate_store")
            telegram_actions = self._import_from_scripts_dir("telegram_actions")

            now = datetime.now(UTC)
            post = extract_candidate.SourcePost(
                post_id=f"manual-{now.strftime('%Y%m%d%H%M%S')}",
                channel=source_channel,
                url=source_url,
                post_date=now.date().isoformat(),
                text=text.strip(),
            )
            cards = extract_candidate.extract_candidates(post)
            merged_cards = deduplicate_candidates.deduplicate_candidates(cards)
            records = candidate_store.load_store(self.store_path)
            result = candidate_store.upsert_candidates(records, merged_cards, new_status="new", now=now)
            candidate_store.write_store(self.store_path, records)

            screen = telegram_actions.handle_action("bond:list:new", self.store_path)
            prefix = (
                "Ручной импорт завершен.\n"
                f"Найдено карточек: {len(cards)}\n"
                f"Новых: {result.inserted}, обновлено: {result.updated}, без изменений: {result.unchanged}\n\n"
            )
            screen["text"] = prefix + screen["text"]
            return screen
        except Exception as exc:  # noqa: BLE001
            return self._unavailable_screen(f"Не удалось разобрать текст облигации: {exc}")

    def _ensure_store_exists(self) -> None:
        if self.store_path.exists():
            return

        seed_path = self._bundled_seed_store_path()
        if not seed_path.exists():
            return

        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed_path, self.store_path)

    def _import_from_scripts_dir(self, module_name: str) -> Any:
        scripts_dir = str(self.scripts_dir)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        existing = sys.modules.get(module_name)
        existing_file = Path(getattr(existing, "__file__", "")).resolve() if existing else None
        if existing_file and not existing_file.is_relative_to(self.scripts_dir.resolve()):
            for name in (
                "telegram_actions",
                "format_candidate",
                "candidate_store",
                "deduplicate_candidates",
                "extract_candidate",
            ):
                sys.modules.pop(name, None)

        return importlib.import_module(module_name)

    @staticmethod
    def inline_keyboard(button_rows: list[list[dict[str, str]]]) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton(item["text"], callback_data=item["callback_data"])
                for item in row
            ]
            for row in button_rows
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def _unavailable_screen(reason: str) -> dict[str, Any]:
        return {
            "text": f"Облигации\n\n{reason}",
            "buttons": [[{"text": "Главное меню", "callback_data": "main:home"}]],
        }
