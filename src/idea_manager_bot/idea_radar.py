"""Personal Telegram idea radar, durable scheduling and feedback in SQLite."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard

from idea_manager_bot.idea_research import IdeaResearch, SOURCES

LOGGER = logging.getLogger(__name__)
MSK = ZoneInfo("Europe/Moscow")


def current_slot(now: datetime) -> datetime | None:
    now = now.astimezone(MSK)
    for hour in (11, 16, 21):
        slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if slot - timedelta(minutes=20) <= now < slot + timedelta(hours=1):
            return slot
    return None


class RadarStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    slot TEXT PRIMARY KEY, state TEXT NOT NULL, report TEXT,
                    card_id INTEGER, message_id INTEGER, error TEXT);
                CREATE TABLE IF NOT EXISTS cards (
                    id INTEGER PRIMARY KEY, slot TEXT NOT NULL, fingerprint TEXT UNIQUE,
                    topic TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS votes (
                    card_id INTEGER NOT NULL REFERENCES cards(id), dimension TEXT NOT NULL,
                    value INTEGER NOT NULL, PRIMARY KEY(card_id, dimension));
                CREATE TABLE IF NOT EXISTS discussion (
                    id INTEGER PRIMARY KEY, card_id INTEGER NOT NULL REFERENCES cards(id),
                    role TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY, card_id INTEGER NOT NULL REFERENCES cards(id));
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def setting(self, key: str, value: str | None = None) -> str | None:
        with self.db() as db:
            if value is not None:
                db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def card(self, card_id: int) -> dict:
        with self.db() as db:
            row = db.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if not row:
            raise ValueError("Карточка не найдена")
        return {**json.loads(row["payload"]), "id": row["id"], "slot": row["slot"]}

    def recent(self, limit: int = 10, offset: int = 0) -> list[dict]:
        with self.db() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM cards ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))]
        return [self.card(i) for i in ids]

    def vote(self, card_id: int, dimension: str, value: int):
        if dimension not in {"idea", "topic"} or value not in {-1, 1}:
            raise ValueError("Invalid feedback")
        self.card(card_id)
        with self.db() as db:
            db.execute("INSERT INTO votes VALUES (?,?,?) ON CONFLICT(card_id,dimension) DO UPDATE SET value=excluded.value", (card_id, dimension, value))

    def remember(self, card_id: int, role: str, text: str):
        with self.db() as db:
            db.execute("INSERT INTO discussion(card_id,role,text,created_at) VALUES (?,?,?,?)",
                       (card_id, role, text, datetime.now(MSK).isoformat()))

    def history(self, card_id: int) -> list[dict]:
        with self.db() as db:
            return [dict(r) for r in reversed(db.execute(
                "SELECT role,text FROM discussion WHERE card_id=? ORDER BY id DESC LIMIT 12", (card_id,)).fetchall())]

    def memory(self) -> dict:
        with self.db() as db:
            votes = [dict(r) for r in db.execute("SELECT c.topic,c.payload,v.dimension,v.value FROM votes v JOIN cards c ON c.id=v.card_id ORDER BY c.id DESC LIMIT 60")]
            comments = [dict(r) for r in db.execute("SELECT c.topic,d.text FROM discussion d JOIN cards c ON c.id=d.card_id WHERE role='user' ORDER BY d.id DESC LIMIT 20")]
            reports = [json.loads(r[0]) for r in db.execute("SELECT report FROM runs WHERE report IS NOT NULL ORDER BY slot DESC LIMIT 21")]
            preferences = [dict(r) for r in db.execute("SELECT c.topic,AVG(v.value) AS preference,COUNT(*) AS votes FROM votes v JOIN cards c ON c.id=v.card_id WHERE dimension='topic' GROUP BY c.topic")]
        return {
            "recent_ideas": [{k: c[k] for k in ("title", "topic", "mechanism_key", "event_key", "fact")} for c in self.recent(60)],
            "feedback": [{"topic": v["topic"], "title": json.loads(v["payload"])["title"], "dimension": v["dimension"], "value": v["value"]} for v in votes],
            "user_comments": [{**c, "text": c["text"][:1000]} for c in comments],
            "recent_scans": [r["topics"] for r in reports],
            "topic_preferences": preferences,
        }

    def topics(self, memory: dict, slot: datetime) -> list[str]:
        keys = list(SOURCES)
        # All eight areas are surveyed daily; feedback adds a personal focus.
        daily = {11: ["venture", "agents", "ru_stocks"], 16: ["crypto", "arbitrage", "ru_stocks"],
                 21: ["memecoins", "predictions", "hyperliquid"]}[slot.hour]
        weights = dict.fromkeys(keys, 1.0)
        for preference in memory.get("topic_preferences", []):
            weights[preference["topic"]] = 1 + .5 * preference["preference"]
        counts = {k: sum(k in scan for scan in memory["recent_scans"]) for k in keys}
        focus = min((k for k in keys if k not in daily), key=lambda k: (counts[k] + 1) / weights[k])
        return daily + [focus]

    def claim(self, slot: str) -> bool:
        with self.db() as db:
            return db.execute("INSERT OR IGNORE INTO runs(slot,state) VALUES (?,'researching')", (slot,)).rowcount == 1

    def complete(self, slot: str, report: dict):
        card = report["idea"]
        card_id = None
        with self.db() as db:
            if card:
                key = (card["mechanism_key"].strip().lower(), card["event_key"].strip().lower())
                fingerprint = hashlib.sha256(json.dumps(key).encode()).hexdigest()
                inserted = db.execute("INSERT OR IGNORE INTO cards(slot,fingerprint,topic,payload) VALUES (?,?,?,?)",
                                      (slot, fingerprint, card["topic"], json.dumps(card, ensure_ascii=False)))
                if inserted.rowcount:
                    card_id = inserted.lastrowid
                else:
                    report["reason"] = "Повтор уже сохранённой гипотезы; новой идеи нет."
            db.execute("UPDATE runs SET state='ready',report=?,card_id=? WHERE slot=?",
                       (json.dumps(report, ensure_ascii=False), card_id, slot))

    def run(self, slot: str) -> dict | None:
        with self.db() as db:
            row = db.execute("SELECT * FROM runs WHERE slot=?", (slot,)).fetchone()
            return dict(row) if row else None

    def state(self, slot: str, state: str, error: str | None = None):
        with self.db() as db:
            db.execute("UPDATE runs SET state=?,error=? WHERE slot=?", (state, error, slot))

    def begin_send(self, slot: str) -> bool:
        with self.db() as db:
            return db.execute("UPDATE runs SET state='sending' WHERE slot=? AND state IN ('ready','failed')", (slot,)).rowcount == 1

    def sent(self, slot: str, message_id: int, card_id: int | None):
        with self.db() as db:
            db.execute("UPDATE runs SET state='sent',message_id=? WHERE slot=?", (message_id, slot))
            if card_id:
                db.execute("INSERT OR REPLACE INTO messages VALUES (?,?)", (message_id, card_id))

    def reply_card(self, message_id: int) -> int | None:
        with self.db() as db:
            row = db.execute("SELECT card_id FROM messages WHERE message_id=?", (message_id,)).fetchone()
            return row[0] if row else None

    def bind(self, message_id: int, card_id: int):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO messages VALUES (?,?)", (message_id, card_id))


def card_keyboard(card_id: int) -> Keyboard:
    def button(text, action):
        return Button(text, callback_data=f"radar:{action}:{card_id}")
    return Keyboard([
        [button("👍 Идея нравится", "like"), button("👎 Не нравится", "dislike")],
        [button("🎯 Больше этой темы", "more"), button("↩️ Меньше этой темы", "less")],
        [button("💬 Обсудить", "discuss"), Button("📚 Архив / настройки", callback_data="radar:home")],
    ])


def render_card(card: dict) -> str:
    labels = {"fact": "Факт / почему сейчас", "hypothesis": "Гипотеза", "edge": "Возможное преимущество",
              "risks": "Что может сломать идею", "test": "Первый эксперимент", "kill": "Критерий отказа"}
    parts = [f"🔭 Радар идей #{card['id']} · {SOURCES[card['topic']][0]}", card["title"]]
    parts += [f"{label}:\n{card[key]}" for key, label in labels.items()]
    parts += ["Источники:\n" + "\n".join(f"{s['url']}\n{s['claim']} (дата: {s['published_date'] or 'не указана'})" for s in card["sources"])]
    return "\n\n".join(parts)


class IdeaRadar:
    def __init__(self, settings, llm):
        self.store = RadarStore(settings.bot_data_dir / "idea-radar" / "radar.sqlite3")
        self.research = IdeaResearch(llm)
        self.enabled = os.getenv("IDEA_RADAR_ENABLED", "0") == "1"
        self.source = os.getenv("IDEA_RADAR_SOURCE", "api")
        self.owner = int(os.getenv("IDEA_RADAR_USER_ID") or settings.pma_operator_user_id or 0)
        self.chat = int(os.getenv("IDEA_RADAR_CHAT_ID") or settings.pma_operator_chat_id or 0)
        self.task = None

    def authorized(self, update) -> bool:
        return bool(self.owner and self.chat and update.effective_user and update.effective_chat
                    and update.effective_user.id == self.owner and update.effective_chat.id == self.chat
                    and update.effective_chat.type == "private")

    async def home(self, update, context, offset: int = 0):
        if not self.authorized(update):
            await update.effective_message.reply_text("Радар доступен только настроенному владельцу в личном чате.")
            return
        context.user_data.pop("radar_card", None)
        context.user_data.pop("pending_action", None)
        self.store.setting("active_card", "")
        paused = self.store.setting("paused") == "1"
        cards = self.store.recent(11, offset)
        rows = [[Button(f"#{c['id']} · {c['title'][:45]}", callback_data=f"radar:show:{c['id']}")] for c in cards[:10]]
        if offset:
            rows.append([Button("← Новее", callback_data=f"radar:page:{max(0, offset-10)}")])
        if len(cards) > 10:
            rows.append([Button("Старее →", callback_data=f"radar:page:{offset+10}")])
        rows += [[Button("▶️ Продолжить" if paused else "⏸ Пауза", callback_data="radar:resume" if paused else "radar:pause")],
                 [Button("🏠 Главное меню", callback_data="main:home")]]
        state = "на паузе" if paused else ("включён через Codex" if self.source == "codex" else "включён" if self.enabled else "ожидает включения")
        await update.effective_message.reply_text(
            f"🔭 Радар идей — {state}\nЕжедневно 11:00, 16:00, 21:00 МСК.\n"
            "По одной проверяемой гипотезе; если хорошей идеи нет, скажу об этом.\n"
            "Оценка идеи и интерес к теме учитываются отдельно. Повторное нажатие меняет оценку.\n"
            "Обсуждение: кнопка или ответ на сообщение. История сохраняется.\n"
            "Источники: официальные документы, исследования, GitHub, открытые сообщества.\n"
            "Закрытые чаты не подключены. Торговые операции радар не выполняет.", reply_markup=Keyboard(rows))

    async def send_card(self, bot, card: dict):
        # A single notification avoids partially delivered cards and retry ambiguity.
        text = render_card(card)
        if len(text.encode("utf-16-le")) // 2 > 4000:
            caption = f"🔭 Радар идей #{card['id']}\n{card['title']}\n\nПолная карточка с источниками — в файле."
            return await bot.send_document(chat_id=self.chat, document=BytesIO(text.encode()),
                filename=f"idea-{card['id']}.md", caption=caption, reply_markup=card_keyboard(card["id"]))
        return await bot.send_message(chat_id=self.chat, text=text, reply_markup=card_keyboard(card["id"]), disable_web_page_preview=True)

    async def leave_on_command(self, update, context):
        if self.authorized(update):
            context.user_data.pop("radar_card", None)
            self.store.setting("active_card", "")

    async def callback(self, update, context):
        if not self.authorized(update):
            await update.effective_message.reply_text("Нет доступа к личному радару.")
            return
        action = update.callback_query.data.split(":")
        if action[1] == "home":
            await self.home(update, context)
            return
        if action[1] in {"pause", "resume"}:
            self.store.setting("paused", "1" if action[1] == "pause" else "0")
            await self.home(update, context)
            return
        try:
            card_id = int(action[2])
            if action[1] == "page":
                await self.home(update, context, max(0, card_id))
                return
            card = self.store.card(card_id)
            if action[1] == "show":
                sent = await self.send_card(context.bot, card)
                self.store.bind(sent.message_id, card_id)
            elif action[1] == "discuss":
                context.user_data["radar_card"] = card_id
                context.user_data.pop("pending_action", None)
                self.store.setting("active_card", str(card_id))
                await self.send_text(update.effective_message, render_card(card))
                await update.effective_message.reply_text("Напиши вопрос или комментарий. Продолжим эту идею; для выхода — главное меню или /radar.")
            elif action[1] in {"like", "dislike", "more", "less"}:
                self.store.vote(card_id, "idea" if action[1] in {"like", "dislike"} else "topic",
                                1 if action[1] in {"like", "more"} else -1)
                await update.effective_message.reply_text("Оценка сохранена и будет учтена в следующих исследованиях.")
        except (ValueError, IndexError):
            await update.effective_message.reply_text("Карточка или действие не найдены. Открой /radar.")

    async def handle_text(self, update, context) -> bool:
        if not self.authorized(update) or not update.message or not update.message.text:
            return False
        reply = update.message.reply_to_message
        card_id = self.store.reply_card(reply.message_id) if reply else None
        card_id = card_id or context.user_data.get("radar_card") or self.store.setting("active_card")
        if not card_id:
            return False
        card_id = int(card_id)
        question = update.message.text[:8000]
        history = self.store.history(card_id)
        self.store.remember(card_id, "user", question)
        await update.message.reply_text("Проверяю вопрос по источникам…")
        try:
            answer = await asyncio.to_thread(self.research.discuss, self.store.card(card_id), history, question)
        except Exception as exc:
            LOGGER.error("Idea discussion failed: %s", type(exc).__name__)
            await update.message.reply_text("Вопрос сохранён, но исследование не завершилось. Попробуй позже; ответ из головы не подставляю.")
            return True
        self.store.remember(card_id, "assistant", answer)
        for message in await self.send_text(update.message, answer):
            self.store.bind(message.message_id, card_id)
        return True

    @staticmethod
    async def send_text(message, text: str):
        # 1800 codepoints remain under Telegram's 4096 UTF-16-unit limit.
        sent = []
        for offset in range(0, len(text), 1800):
            sent.append(await message.reply_text(text[offset:offset + 1800], disable_web_page_preview=True))
        return sent

    async def tick(self, bot, now: datetime | None = None):
        now = now or datetime.now(MSK)
        slot = current_slot(now)
        if not slot or self.store.setting("paused") == "1":
            return
        key = slot.isoformat()
        if self.store.claim(key):
            try:
                memory = self.store.memory()
                report = await asyncio.to_thread(self.research.generate, key, self.store.topics(memory, slot), memory)
                self.store.complete(key, report)
                LOGGER.info("Idea radar research complete for %s", key)
            except Exception as exc:
                LOGGER.error("Idea radar research failed: %s", type(exc).__name__)
                self.store.state(key, "failed", type(exc).__name__)
        row = self.store.run(key)
        if now < slot or self.store.setting("paused") == "1":
            return
        if row["state"] == "researching" and now >= slot + timedelta(minutes=10):
            self.store.state(key, "failed", "Interrupted research; no automatic paid retry")
            row = self.store.run(key)
        await self.deliver(bot, key, slot)

    async def deliver(self, bot, key: str, slot: datetime) -> bool:
        row = self.store.run(key)
        if not row or not self.store.begin_send(key):
            return False
        try:
            if row["card_id"]:
                sent = await self.send_card(bot, self.store.card(row["card_id"]))
            else:
                reason = (json.loads(row["report"])["reason"][:1000] if row["report"] else
                          "Поиск не завершился. Это технический пропуск, а не отсутствие возможностей.")
                sent = await bot.send_message(chat_id=self.chat,
                    text=f"🔭 Радар идей · {slot:%H:%M} МСК\nНовой проверенной идеи в этом выпуске нет.\n{reason}",
                    reply_markup=Keyboard([[Button("📚 Радар", callback_data="radar:home")]]))
            self.store.sent(key, sent.message_id, row["card_id"])
            LOGGER.info("Idea radar delivered %s message=%s", key, sent.message_id)
            return True
        except Exception as exc:
            # Telegram has no idempotency key: an uncertain send is NOT replayed.
            self.store.state(key, "uncertain", type(exc).__name__)
            LOGGER.error("Idea delivery uncertain for %s: %s", key, type(exc).__name__)
            return False

    async def loop(self, bot):
        while True:
            try:
                await self.tick(bot)
            except Exception as exc:
                LOGGER.error("Idea radar cycle failed: %s", type(exc).__name__)
            await asyncio.sleep(30)

    async def delivery_tick(self, bot, now: datetime | None = None):
        now = now or datetime.now(MSK)
        slot = current_slot(now)
        if slot and now >= slot and self.store.setting("paused") != "1":
            row = self.store.run(slot.isoformat())
            if row and row["state"] == "ready" and json.loads(row["report"] or "{}").get("producer") == "codex":
                await self.deliver(bot, slot.isoformat(), slot)

    async def delivery_loop(self, bot):
        while True:
            try:
                await self.delivery_tick(bot)
            except Exception as exc:
                LOGGER.error("Idea radar delivery cycle failed: %s", type(exc).__name__)
            await asyncio.sleep(30)

    def start(self, bot):
        if self.source == "codex" and self.owner and self.chat and not self.enabled:
            self.task = asyncio.create_task(self.delivery_loop(bot), name="idea-radar-delivery")
            LOGGER.info("Idea radar Codex delivery started: 11:00, 16:00, 21:00 Europe/Moscow")
        elif self.source != "codex" and self.enabled and self.owner and self.chat and self.research.llm.client:
            self.task = asyncio.create_task(self.loop(bot), name="idea-radar")
            LOGGER.info("Idea radar started: 11:00, 16:00, 21:00 Europe/Moscow")
        elif self.enabled:
            LOGGER.error("Idea radar configuration invalid; scheduler not started")

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
