"""Paper-only Polymarket UFC singles menu and durable journal."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator

OPENING_BANK = Decimal("300000")
STAKE = Decimal("10000")
PAGE_SIZE = 10
BOUT_PAGE_SIZE = 8


def _rub(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _percent(value: Decimal, places: int = 2) -> str:
    return f"{value:+.{places}f}".replace(".", ",")


def _fighter_lines(fighter: object) -> list[str]:
    if fighter is None:
        return ["Данные бойца пока недоступны."]
    lines = [
        f"{fighter.fighter_name} · {fighter.record_summary}",
        f"Победы: {fighter.wins_summary}",
        f"Поражения: {fighter.losses_summary}",
        "Последние пять выступлений:",
    ]
    for fight in fighter.last_five:
        lines.append(
            f"• {fight.fight_date} · {fight.opponent} · {fight.result}, "
            f"{fight.method}, R{fight.round}"
        )
    if not fighter.last_five:
        lines.append("Нет подтверждённой истории последних пяти выступлений.")
    if fighter.pre_fight_signals:
        lines.append("Предбоевые факторы:")
        lines.extend(f"• {signal.summary_ru}" for signal in fighter.pre_fight_signals)
    return lines


def _card(item: dict, bout: object) -> str:
    lines = [
        f"{item['bout']}",
        f"{bout.weight_class} · {bout.card_segment}",
        f"Исход: {item['question']} — {item['outcome']}",
        f"Коэффициент: {item['decimal']} · ask {item['ask']}",
        f"Снимок: {item['captured_at']} UTC",
        "Цена — ориентир лучшего ask без глубины и комиссии.",
        "",
        *_fighter_lines(bout.fighter_a),
        "",
        *_fighter_lines(bout.fighter_b),
    ]
    return "\n".join(lines)


def _outcome_name(item: dict) -> str:
    question = item["question"]
    outcome = item["outcome"]
    if outcome in item["bout"].split(" — "):
        return f"Победа {outcome}"
    rounds = re.search(r"(?:O/U|Over/Under)\s*(\d+(?:\.\d+)?)\s*Rounds", question, re.I)
    if rounds and outcome.lower() in {"over", "under"}:
        return f"{'ТБ' if outcome.lower() == 'over' else 'ТМ'} {rounds.group(1).replace('.', ',')} раунда"
    if outcome.lower() in {"yes", "no"}:
        return f"{question} — {'да' if outcome.lower() == 'yes' else 'нет'}"
    return f"{question} — {outcome}"


def _history_from_card(card: str) -> str:
    sections = card.split("\n\n", 2)[1:]
    if not sections:
        return "История бойцов пока недоступна."
    formatted = []
    for section in sections:
        lines = []
        for line in section.splitlines():
            if line.startswith("• ") and " · " in line:
                line = " · ".join(line.split(" · ")[:3])
            lines.append(line)
        formatted.append("\n".join(lines))
    return "\n\n".join(formatted)


class UfcPolymarket:
    def __init__(self, data_dir: Path) -> None:
        self.db_path = data_dir / "ufc-polymarket" / "paper.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY, token_id TEXT NOT NULL UNIQUE,
                    event_slug TEXT NOT NULL, event_name TEXT NOT NULL,
                    event_date TEXT NOT NULL, payload TEXT NOT NULL, card TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS catalogues (
                    event_slug TEXT PRIMARY KEY, event_name TEXT NOT NULL,
                    event_date TEXT NOT NULL, captured_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    user_id INTEGER NOT NULL, candidate_id INTEGER NOT NULL,
                    status TEXT NOT NULL, chosen_at TEXT, payout_factor TEXT,
                    PRIMARY KEY (user_id, candidate_id),
                    FOREIGN KEY (candidate_id) REFERENCES candidates(id)
                );
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _latest_event(self) -> sqlite3.Row | None:
        with self._connect() as db:
            return db.execute(
                "SELECT x.event_slug,x.event_name,x.event_date,COUNT(c.id) AS count "
                "FROM catalogues x LEFT JOIN candidates c ON c.event_slug=x.event_slug "
                "GROUP BY x.event_slug ORDER BY x.event_date DESC LIMIT 1"
            ).fetchone()

    def _refresh_if_needed(self) -> sqlite3.Row | None:
        from datetime import date
        from zoneinfo import ZoneInfo

        from ufc_reporter.sources.espn import build_report_from_event_url
        from ufc_reporter.sources.espn_schedule import find_nearest_weekend_event
        from ufc_reporter.polymarket_singles import discover_singles

        today = datetime.now(ZoneInfo("Europe/Moscow")).date()
        latest = self._latest_event()
        if latest and date.fromisoformat(latest["event_date"]) >= today:
            return latest
        upcoming = find_nearest_weekend_event(today)
        if not upcoming:
            return latest
        report = build_report_from_event_url(upcoming.event_url)
        singles = discover_singles(report.event)
        bouts = {bout.bout_id: bout for bout in report.event.bouts}
        bout_order = {bout.bout_id: index for index, bout in enumerate(report.event.bouts)}
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO catalogues VALUES (?,?,?,?)",
                (report.event.event_slug, report.event.event_name, report.event.event_date,
                 datetime.now(UTC).isoformat()),
            )
            for item in singles:
                item = {**item, "bout_order": bout_order[item["bout_id"]]}
                bout = bouts[item["bout_id"]]
                db.execute(
                    "INSERT OR IGNORE INTO candidates "
                    "(token_id,event_slug,event_name,event_date,payload,card) VALUES (?,?,?,?,?,?)",
                    (
                        item["token_id"], item["event_slug"], item["event_name"],
                        item["event_date"], json.dumps(item, ensure_ascii=False),
                        _card(item, bout),
                    ),
                )
        return self._latest_event()

    def import_catalogue(self, raw: bytes, user_id: int) -> dict:
        from ufc_reporter.models import EventSnapshot

        if len(raw) > 2_000_000:
            raise ValueError("Файл списка слишком велик")
        payload = json.loads(raw)
        event = EventSnapshot.from_dict(payload["event"])
        singles = payload["singles"]
        if not isinstance(singles, list) or len(singles) > 1000:
            raise ValueError("Некорректный список исходов")
        bouts = {bout.bout_id: bout for bout in event.bouts}
        bout_order = {bout.bout_id: index for index, bout in enumerate(event.bouts)}
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO catalogues VALUES (?,?,?,?)",
                (event.event_slug, event.event_name, event.event_date, datetime.now(UTC).isoformat()),
            )
            for item in singles:
                if (
                    item.get("event_slug") != event.event_slug
                    or item.get("bout_id") not in bouts
                    or not str(item.get("market_id", "")).isdigit()
                    or not str(item.get("token_id", "")).isdigit()
                    or Decimal(str(item.get("decimal", "0"))) < Decimal("1.70")
                ):
                    raise ValueError("Список содержит некорректный исход")
                item = {**item, "bout_order": bout_order[item["bout_id"]]}
                db.execute(
                    "INSERT OR IGNORE INTO candidates "
                    "(token_id,event_slug,event_name,event_date,payload,card) VALUES (?,?,?,?,?,?)",
                    (item["token_id"], event.event_slug, event.event_name, event.event_date,
                     json.dumps(item, ensure_ascii=False), _card(item, bouts[item["bout_id"]])),
                )
                # Keep the original quote and decision; update only card order for older imports.
                row = db.execute("SELECT id,payload FROM candidates WHERE token_id=?", (item["token_id"],)).fetchone()
                saved = json.loads(row["payload"])
                if saved.get("bout_order") != item["bout_order"]:
                    saved["bout_order"] = item["bout_order"]
                    db.execute("UPDATE candidates SET payload=? WHERE id=?", (json.dumps(saved, ensure_ascii=False), row["id"]))
        return self._list(user_id, 0)

    def handle_action(self, action: str, user_id: int) -> dict:
        try:
            if action == "ufc:poly:stats":
                return self._stats(user_id)
            if action.startswith("ufc:poly:picks:"):
                return self._picks(user_id, max(int(action.rsplit(":", 1)[1]), 0))
            if action.startswith("ufc:poly:show:"):
                return self._show(int(action.rsplit(":", 1)[1]), user_id)
            if action.startswith("ufc:poly:bout:"):
                _, candidate_id, page = action.rsplit(":", 2)
                return self._bout(int(candidate_id), user_id, int(page))
            if action.startswith("ufc:poly:history:"):
                return self._history(int(action.rsplit(":", 1)[1]), user_id)
            if action.startswith("ufc:poly:select:"):
                return self._decide(int(action.rsplit(":", 1)[1]), user_id, "selected")
            if action.startswith("ufc:poly:reject:"):
                return self._decide(int(action.rsplit(":", 1)[1]), user_id, "rejected")
            page = int(action.rsplit(":", 1)[1]) if action.startswith("ufc:poly:list:") else 0
            return self._list(user_id, max(page, 0))
        except Exception as exc:
            return {
                "text": f"Ординары Polymarket временно недоступны: {type(exc).__name__}: {exc}",
                "buttons": [[{"text": "🥊 UFC", "callback_data": "ufc:home"}]],
            }

    def _list(self, user_id: int, page: int) -> dict:
        event = self._refresh_if_needed()
        if not event:
            return {
                "text": "На ближайший турнир список исходов пока не собран.",
                "buttons": [[{"text": "🥊 UFC", "callback_data": "ufc:home"}]],
            }
        with self._connect() as db:
            rows = db.execute(
                "SELECT c.id,c.payload,d.status FROM candidates c "
                "LEFT JOIN decisions d ON d.candidate_id=c.id AND d.user_id=? "
                "WHERE c.event_slug=? ORDER BY c.id",
                (user_id, event["event_slug"]),
            ).fetchall()
        bouts: dict[str, dict] = {}
        for row in rows:
            item = json.loads(row["payload"])
            key = item.get("bout_id") or item["bout"]
            group = bouts.setdefault(key, {"id": row["id"], "item": item, "count": 0, "selected": 0})
            group["count"] += 1
            group["selected"] += row["status"] in {"selected", "settled"}
        ordered = sorted(bouts.values(), key=lambda group: (group["item"].get("bout_order", 999), group["item"]["bout"]))
        visible = ordered[page * BOUT_PAGE_SIZE:(page + 1) * BOUT_PAGE_SIZE]
        buttons = [
            [{"text": f"{group['item']['bout']} · {group['count']} исходов"
                      + (f" · ✅ {group['selected']}" if group["selected"] else ""),
              "callback_data": f"ufc:poly:bout:{group['id']}:0"}]
            for group in visible
        ]
        lines = [
            f"🥊 {event['event_name']}",
            f"Ординары Polymarket: {len(ordered)} боёв, {event['count']} исходов от 1,70.",
            "Выберите бой. Внутри — исходы и история бойцов.",
        ]
        if page:
            buttons.append([{"text": "◀ Назад", "callback_data": f"ufc:poly:list:{page-1}"}])
        if (page + 1) * BOUT_PAGE_SIZE < len(ordered):
            buttons.append([{"text": "Далее ▶", "callback_data": f"ufc:poly:list:{page+1}"}])
        buttons += [
            [{"text": "📊 Мои выборы и статистика", "callback_data": "ufc:poly:stats"}],
            [{"text": "🥊 UFC", "callback_data": "ufc:home"}],
            [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
        ]
        return {"text": "\n".join(lines), "buttons": buttons}

    def _bout(self, candidate_id: int, user_id: int, page: int = 0) -> dict:
        with self._connect() as db:
            anchor = db.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
            if not anchor:
                raise ValueError("Бой не найден")
            anchor_item = json.loads(anchor["payload"])
            rows = db.execute(
                "SELECT c.id,c.payload,d.status FROM candidates c LEFT JOIN decisions d "
                "ON d.candidate_id=c.id AND d.user_id=? WHERE c.event_slug=? ORDER BY c.id",
                (user_id, anchor["event_slug"]),
            ).fetchall()
        key = anchor_item.get("bout_id") or anchor_item["bout"]
        outcomes = [(row, json.loads(row["payload"])) for row in rows]
        outcomes = [(row, item) for row, item in outcomes if (item.get("bout_id") or item["bout"]) == key]
        visible = outcomes[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        buttons = []
        for row, item in visible:
            marker = "✅ " if row["status"] in {"selected", "settled"} else "❌ " if row["status"] == "rejected" else ""
            buttons.append([{"text": f"{marker}{_outcome_name(item)} · {item['decimal']}",
                             "callback_data": f"ufc:poly:show:{row['id']}"}])
        if page:
            buttons.append([{"text": "◀ Исходы", "callback_data": f"ufc:poly:bout:{candidate_id}:{page-1}"}])
        if (page + 1) * PAGE_SIZE < len(outcomes):
            buttons.append([{"text": "Ещё исходы ▶", "callback_data": f"ufc:poly:bout:{candidate_id}:{page+1}"}])
        buttons.extend([
            [{"text": "📋 Последние бои бойцов", "callback_data": f"ufc:poly:history:{candidate_id}"}],
            [{"text": "◀ К боям", "callback_data": "ufc:poly"}],
            [{"text": "🥊 UFC", "callback_data": "ufc:home"}],
            [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
        ])
        return {"text": f"🥊 {anchor_item['bout']}\n{len(outcomes)} исходов от 1,70 · страница {page+1}\n\nВыберите исход или откройте историю бойцов.", "buttons": buttons}

    def _history(self, candidate_id: int, user_id: int) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT payload,card FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise ValueError("Бой не найден")
        item = json.loads(row["payload"])
        return {
            "text": f"📋 {item['bout']}\n\n{_history_from_card(row['card'])}"[:4000],
            "buttons": [
                [{"text": "◀ К исходам боя", "callback_data": f"ufc:poly:bout:{candidate_id}:0"}],
                [{"text": "🥊 UFC", "callback_data": "ufc:home"}],
                [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
            ],
        }

    def _show(self, candidate_id: int, user_id: int) -> dict:
        with self._connect() as db:
            row = db.execute(
                "SELECT c.*,d.status FROM candidates c LEFT JOIN decisions d "
                "ON d.candidate_id=c.id AND d.user_id=? WHERE c.id=?",
                (user_id, candidate_id),
            ).fetchone()
        if not row:
            raise ValueError("Исход не найден")
        item = json.loads(row["payload"])
        status = {"selected": "✅ Выбран", "rejected": "❌ Отклонён", "settled": "Рассчитан"}.get(row["status"], "Не выбран")
        buttons = []
        if row["status"] in {None, "rejected"}:
            buttons.append([{"text": "✅ Выбрать исход", "callback_data": f"ufc:poly:select:{candidate_id}"}])
        if row["status"] is None:
            buttons.append([{"text": "❌ Отклонить исход", "callback_data": f"ufc:poly:reject:{candidate_id}"}])
        buttons += [
            [{"text": "◀ К исходам боя", "callback_data": f"ufc:poly:bout:{candidate_id}:0"}],
            [{"text": "🥊 UFC", "callback_data": "ufc:home"}],
            [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
        ]
        return {
            "text": (f"🥊 {item['bout']}\n\n"
                     f"🎯 Исход\n{_outcome_name(item)}\n\n"
                     f"Коэффициент: {item['decimal']}\nСтатус: {status}\n\n"
                     "Цена — ориентир лучшего ask без глубины и комиссии."),
            "buttons": buttons,
        }

    def _picks(self, user_id: int, page: int) -> dict:
        with self._connect() as db:
            rows = db.execute(
                "SELECT c.id,c.payload,d.status,d.payout_factor FROM decisions d "
                "JOIN candidates c ON c.id=d.candidate_id "
                "WHERE d.user_id=? AND d.status IN ('selected','settled') "
                "ORDER BY d.chosen_at DESC LIMIT ? OFFSET ?",
                (user_id, PAGE_SIZE + 1, page * PAGE_SIZE),
            ).fetchall()
        buttons = []
        for row in rows[:PAGE_SIZE]:
            item = json.loads(row["payload"])
            status = "⏳" if row["status"] == "selected" else (
                "✅" if row["payout_factor"] == "1" else "➗" if row["payout_factor"] == "0.5" else "❌"
            )
            buttons.append([{
                "text": f"{status} {item['bout'][:25]} · {item['outcome'][:15]} · {item['decimal']}",
                "callback_data": f"ufc:poly:show:{row['id']}",
            }])
        if page:
            buttons.append([{"text": "◀ Назад", "callback_data": f"ufc:poly:picks:{page-1}"}])
        if len(rows) > PAGE_SIZE:
            buttons.append([{"text": "Далее ▶", "callback_data": f"ufc:poly:picks:{page+1}"}])
        buttons.extend([
            [{"text": "📊 Статистика", "callback_data": "ufc:poly:stats"}],
            [{"text": "◀ К исходам", "callback_data": "ufc:poly"}],
            [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
        ])
        return {"text": f"Мои выбранные ординары · страница {page+1}", "buttons": buttons}

    def _free_bank(self, db: sqlite3.Connection, user_id: int) -> Decimal:
        rows = db.execute(
            "SELECT d.status,d.payout_factor,c.payload FROM decisions d JOIN candidates c "
            "ON c.id=d.candidate_id WHERE d.user_id=? AND d.status IN ('selected','settled')",
            (user_id,),
        ).fetchall()
        spent = STAKE * len(rows)
        paid = sum(
            (STAKE * Decimal(json.loads(row["payload"])["decimal"]) * Decimal(row["payout_factor"])
             for row in rows if row["status"] == "settled"),
            Decimal(0),
        )
        return OPENING_BANK - spent + paid

    def _decide(self, candidate_id: int, user_id: int, status: str) -> dict:
        from ufc_reporter.polymarket_singles import MARKET_URL, _json_request

        with self._connect() as db:
            row = db.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
            if not row:
                raise ValueError("Исход не найден")
            item = json.loads(row["payload"])
            existing = db.execute(
                "SELECT status FROM decisions WHERE user_id=? AND candidate_id=?",
                (user_id, candidate_id),
            ).fetchone()
            if existing and existing["status"] == "settled":
                return self._show(candidate_id, user_id)
            if existing and existing["status"] == "selected":
                return self._show(candidate_id, user_id)
            if status == "selected" and (not existing or existing["status"] != "selected"):
                market = _json_request(MARKET_URL.format(item["market_id"]))
                if not isinstance(market, dict) or market.get("closed") or market.get("acceptingOrders") is not True:
                    raise ValueError("Рынок уже закрыт; выбор после боя не записан")
                if self._free_bank(db, user_id) < STAKE:
                    raise ValueError("Свободного виртуального банка меньше 10 000 ₽")
            db.execute(
                "INSERT INTO decisions (user_id,candidate_id,status,chosen_at,payout_factor) "
                "VALUES (?,?,?,?,NULL) ON CONFLICT(user_id,candidate_id) DO UPDATE SET "
                "status=excluded.status,chosen_at=excluded.chosen_at,payout_factor=NULL",
                (user_id, candidate_id, status,
                 datetime.now(UTC).isoformat() if status == "selected" else None),
            )
        return self._show(candidate_id, user_id)

    def _stats(self, user_id: int) -> dict:
        from ufc_reporter.polymarket_singles import resolved_payout_factor

        with self._connect() as db:
            rows = db.execute(
                "SELECT d.candidate_id,d.status,c.payload FROM decisions d JOIN candidates c "
                "ON c.id=d.candidate_id WHERE d.user_id=? AND d.status='selected'",
                (user_id,),
            ).fetchall()
        resolved = []
        for row in rows:
            item = json.loads(row["payload"])
            try:
                factor = resolved_payout_factor(item["market_id"], item["token_id"])
            except Exception:
                continue
            if factor is not None:
                resolved.append((str(factor), user_id, row["candidate_id"]))
        with self._connect() as db:
            for update in resolved:
                db.execute(
                    "UPDATE decisions SET status='settled',payout_factor=? "
                    "WHERE user_id=? AND candidate_id=? AND status='selected'",
                    update,
                )
            records = db.execute(
                "SELECT d.status,d.payout_factor,c.payload FROM decisions d JOIN candidates c "
                "ON c.id=d.candidate_id WHERE d.user_id=? AND d.status IN ('selected','settled')",
                (user_id,),
            ).fetchall()
            free = self._free_bank(db, user_id)
        settled = [row for row in records if row["status"] == "settled"]
        wins = sum(Decimal(row["payout_factor"]) == 1 for row in settled)
        partial = sum(Decimal(row["payout_factor"]) == Decimal("0.5") for row in settled)
        payout = sum(
            (STAKE * Decimal(json.loads(row["payload"])["decimal"]) * Decimal(row["payout_factor"])
             for row in settled),
            Decimal(0),
        )
        net = payout - STAKE * len(settled)
        roi = net / (STAKE * len(settled)) * 100 if settled else Decimal(0)
        lines = [
            "📊 Ординары Polymarket · бумажный учёт",
            f"Начальный банк: {_rub(OPENING_BANK)} ₽ · номинал {_rub(STAKE)} ₽",
            f"Выбрано: {len(records)} · рассчитано: {len(settled)} · открыто: {len(records)-len(settled)}",
            f"Побед: {wins} · частичных расчётов: {partial} · поражений: {len(settled)-wins-partial}",
        ]
        if settled:
            lines.append(f"Проходимость: {_percent(Decimal(wins)/len(settled)*100, 1).lstrip('+')}%")
        lines.extend([
            f"ROI: {_percent(roi)}% · результат: {_rub(net)} ₽",
            f"Свободный банк: {_rub(free)} ₽",
            "Расчёт по снимку ask, без глубины и комиссии; реальных ставок нет.",
        ])
        return {
            "text": "\n".join(lines),
            "buttons": [
                [{"text": "📋 Выбранные исходы", "callback_data": "ufc:poly:picks:0"}],
                [{"text": "◀ К списку", "callback_data": "ufc:poly"}],
                [{"text": "🥊 UFC", "callback_data": "ufc:home"}],
                [{"text": "🏠 Главное меню", "callback_data": "main:home"}],
            ],
        }
