from __future__ import annotations

import asyncio
import atexit
import logging
import os
from typing import Any
from urllib.parse import urlparse
from datetime import UTC, datetime, timedelta

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from idea_manager_bot.bond_portfolio import render_cashflow_screen, render_portfolio_screen, write_snapshot
from idea_manager_bot.bond_radar_bridge import BondRadarBridge
from idea_manager_bot.config import Settings, load_settings
from idea_manager_bot.context_loader import load_project_context
from idea_manager_bot.discount_radar_bridge import DiscountRadarBridge
from idea_manager_bot.exporter import SyncExporter
from idea_manager_bot.link_reader import LinkReader
from idea_manager_bot.llm import LLMService
from idea_manager_bot.project_registry import build_project_registry
from idea_manager_bot.storage import IdeaStorage
from idea_manager_bot.t_invest import TInvestClient


logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
LOGGER = logging.getLogger(__name__)

MENU_NEW_IDEA = "Новая идея"
MENU_NEW_CONTEXT = "Новый контекст"
MENU_LIST_IDEAS = "Список идей"
MENU_LIST_CONTEXT = "Список контекста"
MENU_BONDS = "Облигации"
MENU_DISCOUNT = "Дисконт Радар"
MENU_PROJECTS = "Разделы"
MENU_CANCEL = "Отмена"


class IdeaManagerApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.registry = build_project_registry(settings.workspace_root)
        self.storage = IdeaStorage(settings.bot_data_dir)
        self.llm = LLMService(settings.openai_api_key, settings.openai_model)
        self.link_reader = LinkReader()
        self.exporter = SyncExporter(settings)
        self.bond_radar = BondRadarBridge.from_workspace(settings.workspace_root)
        self.discount_radar = DiscountRadarBridge.from_data_dir(settings.bot_data_dir)
        self.t_invest = TInvestClient(settings.t_invest_token)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self._reset_flow(context)
        if not update.message:
            return
        await update.message.reply_text(
            "Это бот-менеджер идей и контекста. Выбери действие в меню ниже.",
            reply_markup=self._main_menu(),
        )

    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        return await self.start(update, context)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        await update.message.reply_text(
            f"`{MENU_NEW_IDEA}`: выбери раздел и отправь идею.\n"
            f"`{MENU_NEW_CONTEXT}`: выбери раздел и отправь полезный материал без обсуждения.\n"
            f"`{MENU_LIST_IDEAS}`: открыть список идей кнопками.\n"
            f"`{MENU_LIST_CONTEXT}`: открыть список контекста кнопками.\n"
            f"`{MENU_BONDS}`: открыть Bond Radar.\n"
            f"`{MENU_DISCOUNT}`: открыть Дисконт Радар.",
            parse_mode="Markdown",
            reply_markup=self._main_menu(),
        )

    async def bonds_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        await self._send_bond_screen(update.message, "bond:home")

    async def discount_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        await self._send_discount_screen(update.message, "discount:home", update.effective_user.id)

    async def myid_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat = update.effective_chat
        user = update.effective_user
        chat_id = chat.id if chat else "n/a"
        user_id = user.id if user else "n/a"
        chat_type = chat.type if chat else "n/a"
        await update.message.reply_text(
            f"chat_id: {chat_id}\n"
            f"user_id: {user_id}\n"
            f"chat_type: {chat_type}",
            reply_markup=self._main_menu(),
        )

    async def projects_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        text = "\n".join(f"- `{item.key}` — {item.description}" for item in self.registry.values())
        await update.message.reply_text(
            f"Доступные разделы:\n{text}",
            parse_mode="Markdown",
            reply_markup=self._main_menu(),
        )

    async def list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        project_key = context.args[0] if context.args else None
        if not project_key:
            await update.message.reply_text(
                "Выбери `Список идей` в меню, чтобы открыть подборку кнопками.",
                reply_markup=self._main_menu(),
            )
            return
        await self._send_idea_list(update.message, project_key)

    async def show_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if not context.args:
            await update.message.reply_text(
                "Лучше открывать идеи через кнопки из списка.",
                reply_markup=self._main_menu(),
            )
            return
        await self._send_idea_details(update.message, context.args[0])

    async def comment_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if len(context.args) < 2:
            await update.message.reply_text(
                "Лучше добавлять комментарий через кнопку внутри идеи.",
                reply_markup=self._main_menu(),
            )
            return

        idea_id = context.args[0]
        comment_text = " ".join(context.args[1:]).strip()
        await self._save_comment(update, context, idea_id, comment_text)

    async def handle_menu_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()
        if text == MENU_NEW_IDEA:
            context.user_data["pending_action"] = "idea"
            await update.message.reply_text(
                "Выбери раздел для новой идеи.",
                reply_markup=self._project_selector("select_idea_project"),
            )
            return

        if text == MENU_NEW_CONTEXT:
            context.user_data["pending_action"] = "context"
            await update.message.reply_text(
                "Выбери раздел для нового контекста.",
                reply_markup=self._project_selector("select_context_project"),
            )
            return

        if text == MENU_LIST_IDEAS:
            await update.message.reply_text(
                "По какому разделу показать идеи?",
                reply_markup=self._project_selector(
                    "list_ideas",
                    include_all=True,
                    include_main_menu=True,
                ),
            )
            return

        if text == MENU_LIST_CONTEXT:
            await update.message.reply_text(
                "По какому разделу показать контекст?",
                reply_markup=self._project_selector(
                    "list_context",
                    include_all=True,
                    include_main_menu=True,
                ),
            )
            return

        if text == MENU_BONDS:
            await self._send_bond_screen(update.message, "bond:home")
            return

        if text == MENU_DISCOUNT:
            await self._send_discount_screen(update.message, "discount:home", update.effective_user.id)
            return

        if text == MENU_PROJECTS:
            await self.projects_command(update, context)
            return

        if text == MENU_CANCEL:
            self._reset_flow(context)
            await update.message.reply_text("Действие отменено.", reply_markup=self._main_menu())
            return

        await self.handle_user_content(update, context)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not query.message:
            return
        await query.answer()

        data = query.data or ""
        if data == "main:home":
            self._reset_flow(context)
            await query.message.reply_text("Главное меню.", reply_markup=self._main_menu())
            return

        if data == "bond:add:manual":
            context.user_data["pending_action"] = "bond_manual_import"
            await query.message.reply_text(
                "Отправь следующим сообщением текст поста или параметры выпуска облигации. "
                "Я попробую извлечь карточку и добавлю ее в Новые кандидаты.",
                reply_markup=self._main_menu(),
            )
            return

        if data.startswith("bond:append-text:"):
            context.user_data["pending_action"] = "bond_append_candidate"
            context.user_data["pending_bond_append_action"] = data
            screen = self.bond_radar.handle_action(data)
            await query.message.reply_text(
                screen["text"][:4000],
                reply_markup=self.bond_radar.inline_keyboard(screen.get("buttons", [])),
            )
            return

        if data.startswith("bond:edit:"):
            context.user_data["pending_action"] = "bond_edit_field"
            context.user_data["pending_bond_edit_action"] = data
            screen = self.bond_radar.handle_action(data)
            await query.message.reply_text(
                screen["text"][:4000],
                reply_markup=self.bond_radar.inline_keyboard(screen.get("buttons", [])),
            )
            return

        if data.startswith("bond:research:"):
            context.user_data["pending_action"] = "bond_research"
            context.user_data["pending_bond_research_action"] = data
            screen = self.bond_radar.handle_action(data)
            await query.message.reply_text(
                screen["text"][:4000],
                reply_markup=self.bond_radar.inline_keyboard(screen.get("buttons", [])),
            )
            return

        if data.startswith("bond:portfolio"):
            await self._send_bond_portfolio_screen(query.message, data)
            return

        if data.startswith("bond:cashflow"):
            await self._send_bond_cashflow_screen(query.message)
            return

        if data.startswith("bond:"):
            await self._send_bond_screen(query.message, data)
            return

        if data == "discount:add":
            context.user_data["pending_action"] = "discount_add_url"
            await query.message.reply_text(
                "Пришли ссылку на товар Ozon.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        if data.startswith("discount:"):
            user_id = update.effective_user.id if update.effective_user else 0
            await self._send_discount_screen(query.message, data, user_id)
            return

        if ":" not in data:
            return
        action, value = data.split(":", 1)

        if action == "select_idea_project":
            context.user_data["pending_action"] = "idea"
            context.user_data["pending_project"] = value
            await query.message.reply_text(
                f"Раздел `{value}` выбран. Отправь идею текстом, ссылкой, голосом или аудио.",
                parse_mode="Markdown",
                reply_markup=self._main_menu(),
            )
            return

        if action == "select_context_project":
            context.user_data["pending_action"] = "context"
            context.user_data["pending_project"] = value
            await query.message.reply_text(
                f"Раздел `{value}` выбран. Отправь контекст текстом, ссылкой, голосом или аудио.",
                parse_mode="Markdown",
                reply_markup=self._main_menu(),
            )
            return

        if action == "list_ideas":
            await self._send_idea_list(query.message, value)
            return

        if action == "show_idea":
            await self._send_idea_details(query.message, value)
            return

        if action == "comment_idea":
            context.user_data["pending_action"] = "comment"
            context.user_data["pending_idea_id"] = value
            await query.message.reply_text(
                "Отправь комментарий к этой идее текстом, голосом или аудио.",
                reply_markup=self._main_menu(),
            )
            return

        if action == "list_context":
            await self._send_context_list(query.message, value)
            return

        if action == "show_context":
            await self._send_context_details(query.message, value)
            return

        if action == "summary_context":
            await self._send_context_summary(query.message, value)
            return

        if action == "context_to_idea":
            await self._convert_context_to_idea(query.message, value)
            return

        if action == "back_list_ideas":
            await self._send_idea_list(query.message, value)
            return

        if action == "back_list_context":
            await self._send_context_list(query.message, value)
            return

    async def handle_user_content(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        pending_action = context.user_data.get("pending_action")
        if pending_action not in {
            "idea",
            "context",
            "comment",
            "append_context_text",
            "bond_manual_import",
            "bond_append_candidate",
            "bond_edit_field",
            "bond_research",
            "discount_add_url",
            "discount_add_target",
        }:
            recovered = await self._try_recover_context_append(update, context)
            if recovered:
                return
            await update.message.reply_text(
                "Сначала выбери действие через меню.",
                reply_markup=self._main_menu(),
            )
            return

        if pending_action in {"discount_add_url", "discount_add_target"}:
            await self._handle_discount_input(update, context, pending_action)
            return

        payload = await self._extract_message_payload(update, context)
        if not payload["normalized_text"] and not payload["raw_input"]:
            await update.message.reply_text("Пока умею принимать только текст, ссылки, голос и аудио.")
            return

        try:
            if pending_action == "bond_manual_import":
                text = self._build_bond_manual_import_text(payload)
                source_url = self._bond_manual_source_url(payload)
                screen = await asyncio.to_thread(
                    self.bond_radar.import_manual_text,
                    text,
                    source_channel=self._bond_manual_source_channel_from_payload(payload, source_url),
                    source_url=source_url,
                )
                self._add_bond_import_diagnostics(screen, payload, text)
                self._reset_flow(context)
                await update.message.reply_text(
                    screen["text"][:4000],
                    reply_markup=self.bond_radar.inline_keyboard(screen.get("buttons", [])),
                )
                return

            if pending_action == "bond_append_candidate":
                append_action = context.user_data.get("pending_bond_append_action")
                if not append_action:
                    self._reset_flow(context)
                    await update.message.reply_text(
                        "Не нашёл карточку для дополнения. Открой карточку заново.",
                        reply_markup=self._main_menu(),
                    )
                    return
                text = self._build_bond_manual_import_text(payload)
                source_url = self._bond_manual_source_url(payload)
                screen = await asyncio.to_thread(
                    self.bond_radar.append_manual_text,
                    append_action,
                    text,
                    source_channel=self._bond_manual_source_channel_from_payload(payload, source_url),
                    source_url=source_url,
                )
                self._reset_flow(context)
                await update.message.reply_text(
                    screen["text"][:4000],
                    reply_markup=self.bond_radar.inline_keyboard(screen.get("buttons", [])),
                )
                return

            if pending_action == "bond_edit_field":
                edit_action = context.user_data.get("pending_bond_edit_action")
                if not edit_action:
                    self._reset_flow(context)
                    await update.message.reply_text(
                        "Не нашёл поле для редактирования. Открой карточку заново.",
                        reply_markup=self._main_menu(),
                    )
                    return
                manual_value = payload["normalized_text"] or payload["raw_input"]
                screen = await asyncio.to_thread(
                    self.bond_radar.edit_manual_field,
                    edit_action,
                    manual_value,
                )
                self._reset_flow(context)
                await update.message.reply_text(
                    screen["text"][:4000],
                    reply_markup=self.bond_radar.inline_keyboard(screen.get("buttons", [])),
                )
                return

            if pending_action == "bond_research":
                research_action = context.user_data.get("pending_bond_research_action")
                if not research_action:
                    self._reset_flow(context)
                    await update.message.reply_text(
                        "Не нашёл карточку для Research Mode. Открой карточку заново.",
                        reply_markup=self._main_menu(),
                    )
                    return
                question = payload["normalized_text"] or payload["raw_input"]
                screen = await asyncio.to_thread(
                    self.bond_radar.research_question,
                    research_action,
                    question,
                    self.llm,
                )
                self._reset_flow(context)
                await update.message.reply_text(
                    screen["text"][:4000],
                    reply_markup=self.bond_radar.inline_keyboard(screen.get("buttons", [])),
                )
                return

            if pending_action == "idea":
                project_key = context.user_data.get("pending_project")
                if project_key not in self.registry:
                    await update.message.reply_text("Сначала выбери раздел для идеи.", reply_markup=self._main_menu())
                    return
                payload["pending_project"] = project_key

                project = self.registry[project_key]
                project_context = load_project_context(project)
                idea_text = self._build_idea_text_for_analysis(payload)
                analysis = await asyncio.to_thread(
                    self.llm.analyze_idea,
                    idea_text,
                    project,
                    project_context,
                    [],
                )
                sync_export_status, sync_export_target = await asyncio.to_thread(
                    self._export_payload,
                    payload,
                    "idea",
                    f"idea-{project.key}-{self._safe_remote_id_suffix(payload)}",
                )
                record = self.storage.create_idea(
                    project=project,
                    source_type=payload["source_type"],
                    raw_input=payload["raw_input"],
                    normalized_text=payload["normalized_text"],
                    links=self.storage.extract_links(payload["raw_input"] or payload["normalized_text"]),
                    analysis=analysis,
                    source_url=payload["source_url"],
                    extracted_content=payload["extracted_content"],
                    link_fetch_status=payload["link_fetch_status"],
                    link_fetch_error=payload["link_fetch_error"],
                    audio_path=payload["audio_path"],
                    sync_export_status=sync_export_status,
                    sync_export_target=sync_export_target,
                )
                self._reset_flow(context)
                warning = self._build_link_warning(payload)
                await update.message.reply_text(
                    f"Идея сохранена в {project.key}.\nФайл: {record.storage_path}\n"
                    f"{warning}{self._build_export_note(record.sync_export_status, record.sync_export_target)}\n\n{analysis[:3200]}",
                    reply_markup=self._idea_actions(record.idea_id, project.key),
                )
                return

            if pending_action == "context":
                project_key = context.user_data.get("pending_project")
                if project_key not in self.registry:
                    await update.message.reply_text("Сначала выбери раздел для контекста.", reply_markup=self._main_menu())
                    return
                payload["pending_project"] = project_key

                project = self.registry[project_key]
                sync_export_status, sync_export_target = await asyncio.to_thread(
                    self._export_payload,
                    payload,
                    "context",
                    f"context-{project.key}-{self._safe_remote_id_suffix(payload)}",
                )
                record = self.storage.create_context(
                    project=project,
                    source_type=payload["source_type"],
                    raw_input=payload["raw_input"],
                    normalized_text=payload["normalized_text"],
                    links=self.storage.extract_links(payload["raw_input"] or payload["normalized_text"]),
                    source_url=payload["source_url"],
                    extracted_content=payload["extracted_content"],
                    link_fetch_status=payload["link_fetch_status"],
                    link_fetch_error=payload["link_fetch_error"],
                    audio_path=payload["audio_path"],
                    sync_export_status=sync_export_status,
                    sync_export_target=sync_export_target,
                )
                self._reset_flow(context)
                warning = self._build_link_warning(payload)
                if payload["source_url"] and payload["link_fetch_status"] != "success":
                    context.user_data["pending_action"] = "append_context_text"
                    context.user_data["pending_context_id"] = record.context_id
                await update.message.reply_text(
                    f"Контекст сохранён в {project.key}.\nФайл: {record.storage_path}"
                    f"{warning}{self._build_export_note(record.sync_export_status, record.sync_export_target)}",
                    reply_markup=self._context_actions(record.context_id, project.key),
                )
                return

            if pending_action == "append_context_text":
                context_id = context.user_data.get("pending_context_id")
                record = self.storage.load_context_record(context_id) if context_id else None
                if not record:
                    self._reset_flow(context)
                    await update.message.reply_text(
                        "Не нашёл запись контекста для обновления. Выбери действие заново.",
                        reply_markup=self._main_menu(),
                    )
                    return

                manual_text = payload["normalized_text"] or payload["raw_input"]
                if not manual_text:
                    await update.message.reply_text("Пришли текст, чтобы я добавил его в контекст.")
                    return

                self._append_manual_text_to_context(record, manual_text)
                self._reset_flow(context)
                await update.message.reply_text(
                    "Текст добавлен в контекстную запись. Теперь её можно открыть и использовать дальше.",
                    reply_markup=self._context_actions(record.context_id, record.project_key),
                )
                return

            idea_id = context.user_data.get("pending_idea_id")
            if not idea_id:
                self._reset_flow(context)
                await update.message.reply_text("Не нашёл идею для комментария.", reply_markup=self._main_menu())
                return
            await self._save_comment(update, context, idea_id, payload["normalized_text"] or payload["raw_input"])
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("handle_user_content failed: %s", exc)
            await update.message.reply_text(
                "Не удалось обработать сообщение из-за технической ошибки. "
                "Попробуй ещё раз или отправь текст короче.",
                reply_markup=self._main_menu(),
            )

    async def _save_comment(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        idea_id: str,
        comment_text: str,
    ) -> None:
        if not update.message:
            return

        record = self.storage.load_record(idea_id)
        if not record:
            self._reset_flow(context)
            await update.message.reply_text("Идея не найдена.", reply_markup=self._main_menu())
            return

        self.storage.add_comment(record, comment_text, self._author_name(update))
        project = self.registry[record.project_key]
        project_context = load_project_context(project)
        comments = [item.text for item in record.comments]
        analysis_input = record.normalized_text
        if record.source_url and record.extracted_content:
            analysis_input = (
                f"Источник: {record.source_url}\n\n"
                f"Текст идеи пользователя:\n{record.normalized_text}\n\n"
                f"Извлечённое содержимое ссылки:\n{record.extracted_content}"
            )
        record.analysis = await asyncio.to_thread(
            self.llm.analyze_idea,
            analysis_input,
            project,
            project_context,
            comments,
        )
        record.updated_at = record.comments[-1].created_at
        self.storage.save_record(record)
        self._reset_flow(context)
        await update.message.reply_text(
            f"Комментарий сохранён.\n\n{record.analysis[:3200]}",
            reply_markup=self._idea_actions(record.idea_id, record.project_key),
        )

    async def _extract_message_payload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
        source_type = "text"
        raw_input = update.message.text or update.message.caption or ""
        normalized_text = raw_input.strip()
        audio_path: str | None = None
        source_url: str | None = None
        extracted_content = ""
        link_fetch_status = "not_applicable"
        link_fetch_error: str | None = None
        telegram_source_channel, telegram_source_url = self._telegram_forward_source(update.message)

        if update.message.voice or update.message.audio:
            source_type = "voice" if update.message.voice else "audio"
            media = update.message.voice or update.message.audio
            telegram_file = await context.bot.get_file(media.file_id)
            suffix = "ogg" if update.message.voice else "mp3"
            temp_path = self.settings.bot_data_dir / "files" / f"telegram-{media.file_id}.{suffix}"
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            await telegram_file.download_to_drive(custom_path=str(temp_path))
            audio_path = str(temp_path)
            raw_input = update.message.caption or f"[{source_type} message]"
            try:
                normalized_text = await asyncio.to_thread(self.llm.transcribe_audio, temp_path)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Failed to transcribe audio: %s", exc)
                normalized_text = raw_input

        links = self.storage.extract_links(raw_input or normalized_text)
        if links:
            source_url = links[0]
            link_result = await asyncio.to_thread(self.link_reader.read, source_url)
            extracted_content = link_result.extracted_content
            link_fetch_status = link_result.status
            link_fetch_error = link_result.error_message

        return {
            "source_type": source_type,
            "raw_input": raw_input,
            "normalized_text": normalized_text,
            "audio_path": audio_path,
            "created_at": self._now_iso(),
            "source_url": source_url,
            "telegram_source_channel": telegram_source_channel,
            "telegram_source_url": self._first_telegram_post_url(links) or telegram_source_url,
            "extracted_content": extracted_content,
            "link_fetch_status": link_fetch_status,
            "link_fetch_error": link_fetch_error,
        }

    @staticmethod
    def _build_bond_manual_import_text(payload: dict[str, Any]) -> str:
        raw_text = (payload.get("normalized_text") or payload.get("raw_input") or "").strip()
        extracted_content = (payload.get("extracted_content") or "").strip()
        if extracted_content and extracted_content not in raw_text:
            return f"{raw_text}\n\n{extracted_content}".strip()
        return raw_text

    @staticmethod
    def _add_bond_import_diagnostics(
        screen: dict[str, Any],
        payload: dict[str, Any],
        parsed_text: str,
    ) -> None:
        if int(screen.get("card_count") or 0) > 0:
            return

        source_url = payload.get("source_url") or payload.get("telegram_source_url")
        if not source_url:
            return

        status = payload.get("link_fetch_status") or "not_applicable"
        extracted_content = (payload.get("extracted_content") or "").strip()
        lines = [
            "",
            "Диагностика ссылки:",
            f"- URL: {source_url}",
            f"- чтение ссылки: {status}",
            f"- извлечено текста: {len(extracted_content)} символов",
        ]
        if payload.get("link_fetch_error"):
            lines.append(f"- ошибка чтения: {payload['link_fetch_error']}")

        preview = " ".join(parsed_text.split())[:700]
        if preview:
            lines.extend(["", "Фрагмент, который ушёл в парсер:", preview])

        screen["text"] = f"{screen['text']}\n" + "\n".join(lines)

    @classmethod
    def _bond_manual_source_url(cls, payload: dict[str, Any]) -> str | None:
        return payload.get("telegram_source_url") or payload.get("source_url")

    @classmethod
    def _bond_manual_source_channel_from_payload(cls, payload: dict[str, Any], source_url: str | None) -> str:
        return payload.get("telegram_source_channel") or cls._bond_manual_source_channel(source_url)

    @staticmethod
    def _bond_manual_source_channel(source_url: str | None) -> str:
        if not source_url:
            return "manual"

        parsed = urlparse(source_url)
        host = parsed.netloc.replace("www.", "")
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if host in {"t.me", "telegram.me"} and path_parts:
            channel = path_parts[1] if path_parts[0] == "s" and len(path_parts) > 1 else path_parts[0]
            return f"@{channel}"
        if host:
            return f"web:{host}"
        return "manual"

    @staticmethod
    def _first_telegram_post_url(links: list[str]) -> str | None:
        for link in links:
            if IdeaManagerApp._is_telegram_post_url(link):
                return link
        return None

    @staticmethod
    def _is_telegram_post_url(url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.replace("www.", "")
        if host not in {"t.me", "telegram.me"}:
            return False
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(path_parts) >= 3 and path_parts[0] == "s":
            return path_parts[2].isdigit()
        if len(path_parts) < 2:
            return False
        return path_parts[1].isdigit()

    @staticmethod
    def _telegram_forward_source(message: Message) -> tuple[str | None, str | None]:
        origin = getattr(message, "forward_origin", None)
        if not origin:
            return None, None

        chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
        if not chat:
            return None, None

        username = getattr(chat, "username", None)
        title = getattr(chat, "title", None)
        channel = f"@{username}" if username else title
        message_id = getattr(origin, "message_id", None)
        if username and message_id:
            return channel, f"https://t.me/{username}/{message_id}"
        return channel, None

    async def _send_idea_list(self, message: Message, project_key: str) -> None:
        all_sections = project_key == "__all__"
        if not all_sections and project_key not in self.registry:
            await message.reply_text("Не знаю такой раздел.", reply_markup=self._main_menu())
            return

        records = self.storage.list_records(project_key=None if all_sections else project_key)
        if not records:
            suffix = "во всех разделах" if all_sections else f"в разделе `{project_key}`"
            await message.reply_text(
                f"Идей пока нет {suffix}.",
                parse_mode="Markdown",
                reply_markup=self._main_menu(),
            )
            return

        keyboard = [
            [InlineKeyboardButton(self._list_label(record), callback_data=f"show_idea:{record.idea_id}")]
            for record in records[:10]
        ]
        keyboard = self._with_main_menu_exit(keyboard)
        header = "Идеи во всех разделах:" if all_sections else f"Идеи в разделе `{project_key}`:"
        await message.reply_text(
            header,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _send_context_list(self, message: Message, project_key: str) -> None:
        all_sections = project_key == "__all__"
        if not all_sections and project_key not in self.registry:
            await message.reply_text("Не знаю такой раздел.", reply_markup=self._main_menu())
            return

        records = self.storage.list_context_records(project_key=None if all_sections else project_key)
        if not records:
            suffix = "во всех разделах" if all_sections else f"в разделе `{project_key}`"
            await message.reply_text(
                f"Контекста пока нет {suffix}.",
                parse_mode="Markdown",
                reply_markup=self._main_menu(),
            )
            return

        keyboard = [
            [InlineKeyboardButton(self._list_label(record), callback_data=f"show_context:{record.context_id}")]
            for record in records[:10]
        ]
        keyboard = self._with_main_menu_exit(keyboard)
        header = "Контекст во всех разделах:" if all_sections else f"Контекст в разделе `{project_key}`:"
        await message.reply_text(
            header,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _send_idea_details(self, message: Message, idea_id: str) -> None:
        record = self.storage.load_record(idea_id)
        if not record:
            await message.reply_text("Идея не найдена.", reply_markup=self._main_menu())
            return

        comments = "\n".join(
            f"- {item.created_at}: {item.text}" for item in record.comments[-5:]
        ) or "- комментариев пока нет"
        await message.reply_text(
            f"*{record.title}*\n"
            f"Проект: `{record.project_key}`\n"
            f"Файл: `{record.storage_path}`\n\n"
            f"*Текст идеи*\n{record.normalized_text}\n\n"
            f"*Ссылка*\n{record.source_url or 'Нет'}\n\n"
            f"*Статус чтения ссылки*\n`{record.link_fetch_status}`\n\n"
            f"*Извлечённое содержимое*\n{(record.extracted_content or 'Нет извлечённого содержимого.')[:2000]}\n\n"
            f"*Анализ*\n{record.analysis[:2500]}\n\n"
            f"*Последние комментарии*\n{comments}",
            reply_markup=self._idea_actions(record.idea_id, record.project_key),
        )

    async def _send_context_details(self, message: Message, context_id: str) -> None:
        record = self.storage.load_context_record(context_id)
        if not record:
            await message.reply_text("Контекст не найден.", reply_markup=self._main_menu())
            return

        await message.reply_text(
            f"*{record.title}*\n"
            f"Проект: `{record.project_key}`\n"
            f"Файл: `{record.storage_path}`\n\n"
            f"*Материал*\n{record.normalized_text or record.raw_input}\n\n"
            f"*Ссылка*\n{record.source_url or 'Нет'}\n\n"
            f"*Статус чтения ссылки*\n`{record.link_fetch_status}`\n\n"
            f"*Извлечённое содержимое*\n{(record.extracted_content or 'Нет извлечённого содержимого.')[:2500]}",
            reply_markup=self._context_actions(record.context_id, record.project_key),
        )

    async def _send_context_summary(self, message: Message, context_id: str) -> None:
        record = self.storage.load_context_record(context_id)
        if not record:
            await message.reply_text("Контекст не найден.", reply_markup=self._main_menu())
            return

        project = self.registry[record.project_key]
        project_context = load_project_context(project)
        source_text = self._build_context_source_text(record)
        summary = await asyncio.to_thread(
            self.llm.summarize_context,
            source_text,
            project,
            project_context,
        )
        await message.reply_text(
            f"Summary для контекста\n\n{summary[:3200]}",
            reply_markup=self._context_actions(record.context_id, record.project_key),
        )

    async def _convert_context_to_idea(self, message: Message, context_id: str) -> None:
        record = self.storage.load_context_record(context_id)
        if not record:
            await message.reply_text("Контекст не найден.", reply_markup=self._main_menu())
            return

        project = self.registry[record.project_key]
        project_context = load_project_context(project)
        idea_text = self._build_context_source_text(record)
        analysis = await asyncio.to_thread(
            self.llm.analyze_idea,
            idea_text,
            project,
            project_context,
            [],
        )
        idea_record = self.storage.create_idea(
            project=project,
            source_type="context-derived",
            raw_input=record.raw_input,
            normalized_text=record.normalized_text or record.raw_input,
            links=record.links,
            analysis=analysis,
            source_url=record.source_url,
            extracted_content=record.extracted_content,
            link_fetch_status=record.link_fetch_status,
            link_fetch_error=record.link_fetch_error,
            audio_path=record.audio_path,
        )
        await message.reply_text(
            f"Из контекста создана новая идея в {project.key}.\n"
            f"Файл: {idea_record.storage_path}\n\n"
            f"{analysis[:2800]}",
            reply_markup=self._idea_actions(idea_record.idea_id, project.key),
        )

    @staticmethod
    def _build_idea_text_for_analysis(payload: dict[str, Any]) -> str:
        if payload["source_url"] and payload["extracted_content"]:
            return (
                f"Источник: {payload['source_url']}\n\n"
                f"Комментарий пользователя:\n{payload['normalized_text'] or payload['raw_input']}\n\n"
                f"Извлечённое содержимое ссылки:\n{payload['extracted_content']}"
            )
        return payload["normalized_text"] or payload["raw_input"]

    @staticmethod
    def _build_context_source_text(record: Any) -> str:
        if record.source_url and record.extracted_content:
            return (
                f"Источник: {record.source_url}\n\n"
                f"Комментарий пользователя:\n{record.normalized_text or record.raw_input}\n\n"
                f"Извлечённое содержимое ссылки:\n{record.extracted_content}"
            )
        return record.normalized_text or record.raw_input

    @staticmethod
    def _build_link_warning(payload: dict[str, Any]) -> str:
        if not payload["source_url"]:
            return ""
        if payload["link_fetch_status"] == "success":
            return "\nСсылка прочитана, URL и содержимое страницы сохранены."
        error_text = payload["link_fetch_error"] or "неизвестная ошибка"
        return (
            "\nСсылку я сохранил, но содержимое страницы прочитать не смог. "
            f"Причина: `{error_text}`. Пришли текст вручную, и я добавлю его в запись."
        )

    def _export_payload(self, payload: dict[str, Any], entity_type: str, remote_id: str) -> tuple[str, str | None]:
        export_payload = {
            "entity_type": entity_type,
            "project_key": payload.get("pending_project") or "",
            "title": self._derive_title(payload),
            "raw_input": payload.get("raw_input") or "",
            "normalized_text": payload.get("normalized_text") or "",
            "source_type": payload.get("source_type") or "unknown",
            "created_at": payload.get("created_at") or "",
            "source_url": payload.get("source_url"),
            "links": self.storage.extract_links(payload.get("raw_input") or payload.get("normalized_text") or ""),
            "extracted_content": payload.get("extracted_content") or "",
            "link_fetch_status": payload.get("link_fetch_status") or "not_applicable",
            "link_fetch_error": payload.get("link_fetch_error"),
        }
        export_payload["created_at"] = export_payload["created_at"] or self._now_iso()

        pending_project = payload.get("pending_project")
        if pending_project:
            export_payload["project_key"] = pending_project

        if not self.exporter.enabled:
            return "not_exported", None

        ok, target = self.exporter.export_record(export_payload, entity_type, remote_id)
        return ("exported" if ok else "export_failed"), target

    @staticmethod
    def _derive_title(payload: dict[str, Any]) -> str:
        source_text = payload.get("normalized_text") or payload.get("raw_input") or "Без названия"
        line = " ".join(source_text.strip().split())
        return line[:80] if line else "Без названия"

    @staticmethod
    def _safe_remote_id_suffix(payload: dict[str, Any]) -> str:
        base = (payload.get("normalized_text") or payload.get("raw_input") or "item").strip().lower()
        # GitHub content path in exporter must stay ASCII-only.
        # str.isalnum() keeps Cyrillic symbols too, which breaks urllib URL handling.
        safe = "".join(char for char in base if ("a" <= char <= "z") or ("0" <= char <= "9"))[:24]
        return safe or "item"

    @staticmethod
    def _now_iso() -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).replace(microsecond=0).isoformat()

    @staticmethod
    def _build_export_note(status: str, target: str | None) -> str:
        if status == "exported":
            return f"\nЗапись экспортирована в sync inbox: `{target}`."
        if status == "export_failed":
            return f"\nЭкспорт в sync inbox не удался: `{target or 'unknown error'}`."
        return ""

    def _append_manual_text_to_context(self, record: Any, manual_text: str) -> None:
        record.raw_input = f"{record.raw_input}\n\n[manual_text]\n{manual_text}".strip()
        record.normalized_text = f"{record.normalized_text}\n\n{manual_text}".strip()
        record.extracted_content = manual_text
        record.link_fetch_status = "manual_text_added"
        self.storage.save_context_record(record)

    async def _try_recover_context_append(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        if not update.message:
            return False
        manual_text = (update.message.text or "").strip()
        if not manual_text:
            return False

        lower_text = manual_text.lower()
        menu_items = {
            MENU_NEW_IDEA.lower(),
            MENU_NEW_CONTEXT.lower(),
            MENU_LIST_IDEAS.lower(),
            MENU_LIST_CONTEXT.lower(),
            MENU_BONDS.lower(),
            MENU_DISCOUNT.lower(),
            MENU_PROJECTS.lower(),
            MENU_CANCEL.lower(),
        }
        if lower_text in menu_items:
            return False

        record = self._find_recent_unresolved_context()
        if not record:
            return False

        self._append_manual_text_to_context(record, manual_text)
        self._reset_flow(context)
        await update.message.reply_text(
            "Я восстановил прерванный сценарий и добавил текст в последний контекст после ошибки чтения ссылки.",
            reply_markup=self._context_actions(record.context_id, record.project_key),
        )
        return True

    def _find_recent_unresolved_context(self) -> Any | None:
        candidates = self.storage.list_context_records()
        now = datetime.now(UTC)
        unresolved_statuses = {"fetch_failed", "unsupported_content", "empty_content"}
        for record in candidates:
            if (record.link_fetch_status or "") not in unresolved_statuses:
                continue
            if record.extracted_content:
                continue
            created = self._parse_iso_datetime(record.created_at)
            if not created:
                continue
            if now - created > timedelta(hours=2):
                continue
            return record
        return None

    @staticmethod
    def _parse_iso_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            return None

    @staticmethod
    def _list_label(record: Any) -> str:
        title = (getattr(record, "title", "") or "").strip()
        source_url = getattr(record, "source_url", None) or ""
        extracted = (getattr(record, "extracted_content", "") or "").strip()

        is_url_title = title.startswith("http://") or title.startswith("https://")
        if is_url_title or (source_url and title == source_url):
            host = urlparse(source_url or title).netloc.replace("www.", "")
            summary = " ".join(extracted.split())
            if summary:
                label = f"{host}: {summary}" if host else summary
                return label[:60]
            if host:
                return f"{host}: ссылка"[:60]
            return "Ссылка без описания"

        if not title:
            return "Без названия"
        return title[:60]

    @staticmethod
    def _with_main_menu_exit(
        keyboard: list[list[InlineKeyboardButton]],
    ) -> list[list[InlineKeyboardButton]]:
        return [*keyboard, [InlineKeyboardButton("Главное меню", callback_data="main:home")]]

    async def _send_bond_screen(self, message: Message, action: str) -> None:
        screen = self.bond_radar.handle_action(action)
        await message.reply_text(
            screen["text"][:4000],
            reply_markup=self.bond_radar.inline_keyboard(screen.get("buttons", [])),
        )

    async def _send_bond_portfolio_screen(self, message: Message, action: str) -> None:
        screen = await asyncio.to_thread(self._build_bond_portfolio_screen, action)
        await message.reply_text(
            screen["text"][:4000],
            reply_markup=self.bond_radar.inline_keyboard(screen.get("buttons", [])),
        )

    async def _send_bond_cashflow_screen(self, message: Message) -> None:
        screen = await asyncio.to_thread(self._build_bond_cashflow_screen)
        await message.reply_text(
            screen["text"][:4000],
            reply_markup=self.bond_radar.inline_keyboard(screen.get("buttons", [])),
        )

    async def _send_discount_screen(self, message: Message, action: str, user_id: int) -> None:
        screen = await asyncio.to_thread(
            self.discount_radar.handle_action,
            action,
            user_id=user_id,
        )
        await message.reply_text(
            screen["text"][:4000],
            reply_markup=self.discount_radar.inline_keyboard(screen.get("buttons", [])),
        )

    async def _handle_discount_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        pending_action: str,
    ) -> None:
        if not update.message:
            return
        text = (update.message.text or "").strip()

        if pending_action == "discount_add_url":
            if not self.discount_radar.is_ozon_url(text):
                await update.message.reply_text(
                    "Это не похоже на ссылку Ozon. Пришли ссылку вида https://www.ozon.ru/...",
                    reply_markup=ReplyKeyboardRemove(),
                )
                return
            context.user_data["pending_discount_url"] = text
            context.user_data["pending_action"] = "discount_add_target"
            await update.message.reply_text(
                "Укажи последнюю известную цену в рублях, например 1490.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        reference_price = self.discount_radar.parse_price(text)
        if reference_price is None or reference_price <= 0:
            await update.message.reply_text(
                "Не понял цену. Напиши число, например 1490.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        url = context.user_data.get("pending_discount_url")
        if not url:
            self._reset_flow(context)
            await update.message.reply_text(
                "Не нашёл ссылку товара. Начни добавление заново.",
                reply_markup=self._main_menu(),
            )
            return

        user_id = update.effective_user.id if update.effective_user else 0
        screen = await asyncio.to_thread(
            self.discount_radar.add_product,
            user_id=user_id,
            url=url,
            reference_price=reference_price,
        )
        self._reset_flow(context)
        await update.message.reply_text(
            screen["text"][:4000],
            reply_markup=self.discount_radar.inline_keyboard(screen.get("buttons", [])),
        )

    def _build_bond_portfolio_screen(self, action: str) -> dict[str, Any]:
        if not self.t_invest.configured:
            return {
                "text": (
                    "💼 Портфель облигаций\n\n"
                    "T_INVEST_TOKEN не настроен. Добавь read-only токен Т-Инвестиций в Railway Variables."
                ),
                "buttons": [[{"text": "📡 К облигациям", "callback_data": "bond:home"}]],
            }
        sort = self._bond_portfolio_sort(action)
        try:
            snapshot = self.t_invest.fetch_portfolio_snapshot(self.settings.t_invest_account_id)
            snapshot_dict = {
                "fetched_at": snapshot.fetched_at,
                "account_id": snapshot.account_id,
                "positions": snapshot.positions,
            }
            write_snapshot(self.settings.bot_data_dir / "bond-radar" / "portfolio_snapshot.json", snapshot_dict)
            return render_portfolio_screen(snapshot_dict, sort=sort)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("T-Invest portfolio refresh failed")
            return {
                "text": f"💼 Портфель облигаций\n\nНе удалось обновить портфель через T-Invest API: {exc}",
                "buttons": [[{"text": "📡 К облигациям", "callback_data": "bond:home"}]],
            }

    def _build_bond_cashflow_screen(self) -> dict[str, Any]:
        if not self.t_invest.configured:
            return {
                "text": (
                    "💸 Cashflow на 3 месяца\n\n"
                    "T_INVEST_TOKEN не настроен. Добавь read-only токен Т-Инвестиций в Railway Variables."
                ),
                "buttons": [[{"text": "📡 К облигациям", "callback_data": "bond:home"}]],
            }
        try:
            snapshot = self.t_invest.fetch_cashflow_snapshot(self.settings.t_invest_account_id)
            snapshot_dict = {
                "fetched_at": snapshot.fetched_at,
                "account_id": snapshot.account_id,
                "events": snapshot.events,
            }
            write_snapshot(self.settings.bot_data_dir / "bond-radar" / "cashflow_snapshot.json", snapshot_dict)
            return render_cashflow_screen(snapshot_dict)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("T-Invest cashflow refresh failed")
            return {
                "text": f"💸 Cashflow на 3 месяца\n\nНе удалось обновить cashflow через T-Invest API: {exc}",
                "buttons": [[{"text": "📡 К облигациям", "callback_data": "bond:home"}]],
            }

    @staticmethod
    def _bond_portfolio_sort(action: str) -> str:
        prefix = "bond:portfolio:"
        if action.startswith(prefix):
            return action.removeprefix(prefix)
        return "sum_desc"

    def _project_selector(
        self,
        action: str,
        include_all: bool = False,
        include_main_menu: bool = False,
    ) -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton(project.label, callback_data=f"{action}:{project.key}")]
            for project in self.registry.values()
        ]
        if include_all:
            keyboard.append([InlineKeyboardButton("Все разделы", callback_data=f"{action}:__all__")])
        if include_main_menu:
            keyboard.append([InlineKeyboardButton("Главное меню", callback_data="main:home")])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def _idea_actions(idea_id: str, project_key: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Открыть идею", callback_data=f"show_idea:{idea_id}")],
                [InlineKeyboardButton("Добавить комментарий", callback_data=f"comment_idea:{idea_id}")],
                [InlineKeyboardButton("Назад к списку", callback_data=f"back_list_ideas:{project_key}")],
                [InlineKeyboardButton("Главное меню", callback_data="main:home")],
            ]
        )

    @staticmethod
    def _context_actions(context_id: str, project_key: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Открыть контекст", callback_data=f"show_context:{context_id}")],
                [InlineKeyboardButton("Попросить summary", callback_data=f"summary_context:{context_id}")],
                [InlineKeyboardButton("Сделать из контекста идею", callback_data=f"context_to_idea:{context_id}")],
                [InlineKeyboardButton("Назад к списку", callback_data=f"back_list_context:{project_key}")],
                [InlineKeyboardButton("Главное меню", callback_data="main:home")],
            ]
        )

    @staticmethod
    def _main_menu() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            [
                [KeyboardButton(MENU_NEW_IDEA), KeyboardButton(MENU_NEW_CONTEXT)],
                [KeyboardButton(MENU_LIST_IDEAS), KeyboardButton(MENU_LIST_CONTEXT)],
                [KeyboardButton(MENU_BONDS), KeyboardButton(MENU_DISCOUNT)],
                [KeyboardButton(MENU_CANCEL)],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
            is_persistent=False,
        )

    @staticmethod
    def _reset_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
        context.user_data.pop("pending_action", None)
        context.user_data.pop("pending_project", None)
        context.user_data.pop("pending_idea_id", None)
        context.user_data.pop("pending_context_id", None)
        context.user_data.pop("pending_bond_append_action", None)
        context.user_data.pop("pending_bond_edit_action", None)
        context.user_data.pop("pending_bond_research_action", None)
        context.user_data.pop("pending_discount_url", None)

    @staticmethod
    def _author_name(update: Update) -> str:
        user = update.effective_user
        if not user:
            return "unknown"
        return user.full_name or user.username or str(user.id)


async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "Запустить бота"),
        BotCommand("menu", "Открыть меню"),
        BotCommand("help", "Подсказка"),
        BotCommand("myid", "Показать chat_id"),
        BotCommand("bonds", "Открыть Bond Radar"),
        BotCommand("discount", "Открыть Дисконт Радар"),
        BotCommand("projects", "Список разделов"),
        BotCommand("list", "Список идей"),
        BotCommand("show", "Показать идею по ID"),
        BotCommand("comment", "Добавить комментарий к идее"),
    ]
    await application.bot.set_my_commands(commands)


def build_application(settings: Settings) -> Application:
    app_logic = IdeaManagerApp(settings)
    application = ApplicationBuilder().token(settings.telegram_bot_token).post_init(post_init).build()

    application.add_handler(CommandHandler("start", app_logic.start))
    application.add_handler(CommandHandler("menu", app_logic.menu_command))
    application.add_handler(CommandHandler("help", app_logic.help_command))
    application.add_handler(CommandHandler("myid", app_logic.myid_command))
    application.add_handler(CommandHandler("bonds", app_logic.bonds_command))
    application.add_handler(CommandHandler("discount", app_logic.discount_command))
    application.add_handler(CommandHandler("projects", app_logic.projects_command))
    application.add_handler(CommandHandler("list", app_logic.list_command))
    application.add_handler(CommandHandler("show", app_logic.show_command))
    application.add_handler(CommandHandler("comment", app_logic.comment_command))
    application.add_handler(CallbackQueryHandler(app_logic.handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, app_logic.handle_menu_text))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, app_logic.handle_user_content))
    return application


def main() -> None:
    settings = load_settings()
    for project in build_project_registry(settings.workspace_root).values():
        project.inbox_dir.mkdir(parents=True, exist_ok=True)
        project.context_dir.mkdir(parents=True, exist_ok=True)

    lock_dir = settings.bot_data_dir / "run"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "instance.lock"
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(lock_fd, str(os.getpid()).encode("utf-8"))
        os.close(lock_fd)
    except FileExistsError:
        print("Another bot instance is already running. Stop it first and restart.")
        return

    def _cleanup_lock() -> None:
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass

    atexit.register(_cleanup_lock)

    # Python 3.14 no longer provides a default event loop in main thread.
    asyncio.set_event_loop(asyncio.new_event_loop())
    application = build_application(settings)
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        _cleanup_lock()
