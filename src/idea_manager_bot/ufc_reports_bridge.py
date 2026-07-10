from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


REPO_ROOT = Path(__file__).resolve().parents[2]
UFC_REPORTER_SRC = REPO_ROOT / "services" / "ufc-reporter" / "src"


@dataclass(frozen=True)
class UfcReportSummary:
    slug: str
    event_name: str
    event_date: str
    confirmed_bouts: str
    generated_at: str
    markdown_path: str


class UfcReportsBridge:
    def handle_action(self, action: str) -> dict[str, Any]:
        if action == "ufc:home":
            return self._home_screen()
        if action == "ufc:list":
            return self._list_screen()
        if action.startswith("ufc:show:"):
            return self._show_report_screen(action.removeprefix("ufc:show:"))
        return self._home_screen()

    def run_full_report(self) -> dict[str, Any]:
        try:
            result = self._run_monitoring_cycle(mode="baseline", send="telegram")
        except Exception as exc:  # noqa: BLE001
            return self._error_screen("Не удалось запустить полный UFC-отчёт.", exc)
        return self._result_screen(
            title="🥊 Полный UFC-отчёт",
            result=result,
            changed_text="Полный отчёт собран и отправлен в Telegram.",
            unchanged_text="Полный отчёт не был отправлен.",
        )

    def run_incremental_check(self) -> dict[str, Any]:
        try:
            result = self._run_monitoring_cycle(mode="incremental", send="telegram")
            if (
                result.status == "skipped"
                and result.reason == "No active weekend monitoring window is open."
            ):
                baseline_result = self._run_monitoring_cycle(mode="baseline", send="telegram")
                return self._result_screen(
                    title="🥊 Проверка изменений UFC",
                    result=baseline_result,
                    changed_text=(
                        "Активного baseline не было, поэтому вместо diff собран и отправлен "
                        "полный отчёт."
                    ),
                    unchanged_text="Активного baseline не было, полный отчёт не отправлен.",
                )
        except Exception as exc:  # noqa: BLE001
            return self._error_screen("Не удалось проверить UFC-изменения.", exc)
        return self._result_screen(
            title="🥊 Проверка изменений UFC",
            result=result,
            changed_text="Найдены изменения. В Telegram отправлен файл только с изменениями.",
            unchanged_text="Изменений относительно последней отправленной версии нет.",
        )

    def send_existing_report(self, slug: str) -> dict[str, Any]:
        try:
            self._ensure_ufc_reporter_path()
            from ufc_reporter.rendering import render_report
            from ufc_reporter.state_store import load_snapshot, write_rendered_markdown
            from ufc_reporter.telegram import send_report_delivery

            report = load_snapshot(slug)
            markdown_path = self._markdown_path_for_slug(slug)
            if not markdown_path.exists():
                markdown_path = write_rendered_markdown(
                    report.event.event_slug,
                    render_report(report),
                    "rendered-report.md",
                )
            send_report_delivery(
                report=report,
                markdown_path=markdown_path,
                report_kind="baseline",
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_screen("Не удалось отправить выбранный UFC-отчёт.", exc)
        return {
            "text": "\n".join(
                [
                    "🥊 UFC-отчёт отправлен.",
                    f"Турнир: {report.event.event_name}",
                    f"Дата: {report.event.event_date}",
                ]
            ),
            "buttons": self._back_buttons(),
        }

    def _home_screen(self) -> dict[str, Any]:
        return {
            "text": "\n".join(
                [
                    "🥊 UFC",
                    "",
                    "Здесь можно посмотреть уже собранные отчёты или принудительно запустить сборку.",
                    "",
                    "Полный отчёт заново собирает весь ближайший UFC Fight Night или номерной UFC.",
                    "Проверка изменений отправляет только diff, если baseline уже был создан.",
                ]
            ),
            "buttons": [
                [{"text": "📋 Список отчётов", "callback_data": "ufc:list"}],
                [{"text": "🚀 Запустить полный отчёт", "callback_data": "ufc:run-full"}],
                [{"text": "🔎 Проверить изменения", "callback_data": "ufc:run-changes"}],
                [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
            ],
        }

    def _list_screen(self) -> dict[str, Any]:
        try:
            reports = self._list_reports(limit=10)
        except Exception as exc:  # noqa: BLE001
            return self._error_screen("Не удалось прочитать список UFC-отчётов.", exc)
        if not reports:
            return {
                "text": "🥊 UFC\n\nСохранённых отчётов пока не найдено.",
                "buttons": self._back_buttons(),
            }
        buttons = []
        lines = ["🥊 Последние UFC-отчёты", ""]
        for index, report in enumerate(reports, start=1):
            lines.append(
                f"{index}. {report.event_date} — {report.event_name} "
                f"({report.confirmed_bouts} боёв)"
            )
            buttons.append(
                [
                    {
                        "text": f"{report.event_date} · {report.event_name[:32]}",
                        "callback_data": f"ufc:show:{report.slug}",
                    }
                ]
            )
        buttons.extend(self._back_buttons())
        return {"text": "\n".join(lines), "buttons": buttons}

    def _show_report_screen(self, slug: str) -> dict[str, Any]:
        try:
            report = self._report_summary(slug)
        except Exception as exc:  # noqa: BLE001
            return self._error_screen("Не удалось открыть UFC-отчёт.", exc)
        return {
            "text": "\n".join(
                [
                    "🥊 UFC-отчёт",
                    f"Турнир: {report.event_name}",
                    f"Дата: {report.event_date}",
                    f"Боёв: {report.confirmed_bouts}",
                    f"Собран: {report.generated_at}",
                    f"Файл: {report.markdown_path}",
                ]
            ),
            "buttons": [
                [{"text": "📤 Отправить файл", "callback_data": f"ufc:send:{slug}"}],
                [{"text": "📋 Список отчётов", "callback_data": "ufc:list"}],
                [{"text": "🥊 UFC", "callback_data": "ufc:home"}],
                [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
            ],
        }

    def _result_screen(
        self,
        *,
        title: str,
        result: Any,
        changed_text: str,
        unchanged_text: str,
    ) -> dict[str, Any]:
        status_line = changed_text if result.changed else unchanged_text
        return {
            "text": "\n".join(
                [
                    title,
                    f"status={result.status}",
                    f"mode={result.mode}",
                    f"reason={result.reason}",
                    f"event={result.event_slug}",
                    f"date={result.event_date}",
                    "",
                    status_line,
                ]
            ),
            "buttons": self._back_buttons(),
        }

    def _error_screen(self, intro: str, exc: Exception) -> dict[str, Any]:
        return {
            "text": f"{intro}\n\nОшибка: `{type(exc).__name__}: {exc}`",
            "buttons": self._back_buttons(),
        }

    def _run_monitoring_cycle(self, *, mode: str, send: str) -> Any:
        self._ensure_ufc_reporter_path()
        from ufc_reporter.monitoring import run_monitoring_cycle

        return run_monitoring_cycle(mode=mode, send=send, weekend_only=True)

    def _list_reports(self, *, limit: int) -> list[UfcReportSummary]:
        self._ensure_ufc_reporter_path()
        from ufc_reporter.config import get_paths
        from ufc_reporter.state_store import ensure_runtime_dirs

        ensure_runtime_dirs()
        reports_dir = get_paths().runtime_reports_dir
        summaries: list[UfcReportSummary] = []
        for snapshot_path in reports_dir.glob("*/report_snapshot.json"):
            try:
                summaries.append(self._report_summary(snapshot_path.parent.name))
            except Exception:
                continue
        summaries.sort(key=lambda item: (item.event_date, item.generated_at), reverse=True)
        return summaries[:limit]

    def _report_summary(self, slug: str) -> UfcReportSummary:
        self._ensure_ufc_reporter_path()
        from ufc_reporter.state_store import load_snapshot

        report = load_snapshot(slug)
        markdown_path = self._markdown_path_for_slug(report.event.event_slug)
        return UfcReportSummary(
            slug=report.event.event_slug,
            event_name=report.event.event_name,
            event_date=report.event.event_date,
            confirmed_bouts=report.event.confirmed_bouts,
            generated_at=report.generated_at,
            markdown_path=str(markdown_path),
        )

    def _markdown_path_for_slug(self, slug: str) -> Path:
        self._ensure_ufc_reporter_path()
        from ufc_reporter.config import get_paths

        return get_paths().runtime_reports_dir / slug / "rendered-report.md"

    @staticmethod
    def inline_keyboard(button_rows: list[list[dict[str, str]]]) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        button["text"],
                        callback_data=button["callback_data"],
                    )
                    for button in row
                ]
                for row in button_rows
            ]
        )

    @staticmethod
    def _back_buttons() -> list[list[dict[str, str]]]:
        return [
            [{"text": "🥊 UFC", "callback_data": "ufc:home"}],
            [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
        ]

    @staticmethod
    def _ensure_ufc_reporter_path() -> None:
        if find_spec("ufc_reporter") is not None:
            return
        explicit_path = os.environ.get("UFC_REPORTER_SRC", "").strip()
        current_file = Path(__file__).resolve()
        candidates = [Path(explicit_path)] if explicit_path else []
        candidates.extend(
            [
                UFC_REPORTER_SRC,
                Path.cwd() / "services" / "ufc-reporter" / "src",
                Path("/app/services/ufc-reporter/src"),
                Path("/workspace/services/ufc-reporter/src"),
                Path("/app/src/services/ufc-reporter/src"),
            ]
        )
        candidates.extend(
            parent / "services" / "ufc-reporter" / "src"
            for parent in current_file.parents
        )
        checked_paths: list[str] = []
        for candidate in candidates:
            if not candidate:
                continue
            checked_paths.append(str(candidate))
            if (candidate / "ufc_reporter").is_dir():
                raw_path = str(candidate)
                if raw_path not in sys.path:
                    sys.path.insert(0, raw_path)
                return
        raise RuntimeError(
            "UFC reporter source is not available. Expected services/ufc-reporter/src "
            "or env UFC_REPORTER_SRC. Checked: "
            + ", ".join(dict.fromkeys(checked_paths))
        )
