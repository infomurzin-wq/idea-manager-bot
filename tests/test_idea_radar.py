from datetime import datetime, UTC
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from idea_manager_bot.idea_radar import IdeaRadar, RadarStore, MSK, current_slot, card_keyboard
from idea_manager_bot.idea_research import validate_card, evidence_urls
from idea_manager_bot.radar_codex_bridge import context as codex_context, publish as codex_publish


def card():
    return dict(topic="agents", title="Проверяемая гипотеза", mechanism_key="evals", event_key="release-2026-09",
                fact="Найден публичный релиз", hypothesis="Гипотеза: уменьшится число ошибок",
                edge="Нужно проверить", risks="Нерепрезентативная выборка", test="20 задач, 2 часа, доля ошибок",
                kill="Нет улучшения", sources=[
                    dict(url="https://www.anthropic.com/engineering/test", claim="Метод", published_date=None),
                    dict(url="https://github.com/example/repo", claim="Реализация", published_date="2026-09-24")])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "radar.sqlite3"
        self.store = RadarStore(self.path)

    def insert(self, slot="2026-09-24T11:00:00+03:00"):
        report = dict(idea=card(), reason="Подтверждено", topics=["agents", "crypto"])
        self.assertTrue(self.store.claim(slot))
        self.store.complete(slot, report)
        return self.store.run(slot)

    def test_atomic_slot_claim_and_restart(self):
        self.assertTrue(self.store.claim("slot"))
        self.assertFalse(RadarStore(self.path).claim("slot"))

    def test_votes_replace_and_separate_dimensions(self):
        row = self.insert()
        i = row["card_id"]
        self.store.vote(i, "idea", -1)
        self.store.vote(i, "idea", 1)
        self.store.vote(i, "topic", -1)
        memory = RadarStore(self.path).memory()
        self.assertEqual(2, len(memory["feedback"]))
        self.assertEqual({("idea", 1), ("topic", -1)}, {(v["dimension"], v["value"]) for v in memory["feedback"]})

    def test_dedup_and_history_survive_restart(self):
        row = self.insert()
        self.store.remember(row["card_id"], "user", "Интересует другой риск")
        second = self.insert("2026-09-24T15:00:00+03:00")
        self.assertIsNone(second["card_id"])
        self.assertEqual(1, len(self.store.recent()))
        self.assertIn("другой риск", RadarStore(self.path).memory()["user_comments"][0]["text"])

    def test_delivery_claim_is_atomic_and_replies_persist(self):
        row = self.insert()
        self.assertTrue(self.store.begin_send(row["slot"]))
        self.assertFalse(self.store.begin_send(row["slot"]))
        self.store.sent(row["slot"], 50, row["card_id"])
        self.assertEqual(row["card_id"], RadarStore(self.path).reply_card(50))

    def test_topic_feedback_affects_ranking_and_keeps_exploration(self):
        memory = dict(feedback=[], topic_preferences=[dict(topic="crypto", preference=1)],
                      recent_scans=[list(__import__('idea_manager_bot.idea_research', fromlist=['SOURCES']).SOURCES)])
        topics = self.store.topics(memory, datetime(2026, 9, 24, 11, tzinfo=MSK))
        self.assertIn("crypto", topics)
        self.assertIn("ru_stocks", topics)
        self.assertEqual(4, len(set(topics)))
        afternoon = self.store.topics(memory, datetime(2026, 9, 24, 16, tzinfo=MSK))
        self.assertIn("ru_stocks", afternoon)
        self.assertEqual(4, len(set(afternoon)))
        scanned = set()
        for hour in (11, 16, 21):
            scanned.update(self.store.topics(memory, datetime(2026, 9, 24, hour, tzinfo=MSK)))
        self.assertEqual(8, len(scanned))

    def test_source_validation_rejects_invented_url(self):
        c = card()
        urls = {s["url"] for s in c["sources"]}
        self.assertEqual(c, validate_card(c, urls))
        c["topic"] = "ru_stocks"
        self.assertEqual(c, validate_card(c, urls))
        c["sources"][0]["url"] = "https://invented.invalid/page"
        with self.assertRaises(ValueError):
            validate_card(c, urls)

    def test_detailed_experiment_is_not_rejected_by_editorial_length_target(self):
        c = card()
        c["test"] = "Проверить исполнения и комиссии на выборке. " * 15
        self.assertEqual(c, validate_card(c, {s["url"] for s in c["sources"]}))

    def test_source_validation_rejects_duplicate_document_and_bad_date(self):
        for change in ("domain", "date"):
            c = card()
            if change == "domain": c["sources"][1]["url"] = c["sources"][0]["url"]
            else: c["sources"][1]["published_date"] = "yesterday"
            with self.assertRaises(ValueError):
                validate_card(c, {s["url"] for s in c["sources"]})

    def test_navigation_pages_cannot_substitute_for_evidence(self):
        c = card()
        c["sources"][0]["url"] = "https://dune.com/discover/content/trending?utm_source=test"
        with self.assertRaisesRegex(ValueError, "navigation index"):
            validate_card(c, {s["url"] for s in c["sources"]})

    def test_no_search_no_ideas(self):
        with self.assertRaises(ValueError):
            evidence_urls(NS(model_dump=lambda: {"output": []}))

    def test_nullable_reasoning_content_in_live_api_response(self):
        data = {"output": [{"type": "reasoning", "content": None},
                           {"type": "web_search_call", "status": "completed", "content": None,
                            "action": {"sources": [{"url": "https://example.com/evidence"}]}}]}
        self.assertEqual({"https://example.com/evidence"}, evidence_urls(NS(model_dump=lambda: data)))

    def test_schedule_utc_boundaries_and_no_old_backfill(self):
        self.assertIsNone(current_slot(datetime(2026, 9, 24, 7, 39, tzinfo=UTC)))
        self.assertEqual(11, current_slot(datetime(2026, 9, 24, 7, 40, tzinfo=UTC)).hour)
        self.assertIsNone(current_slot(datetime(2026, 9, 24, 12, 0, tzinfo=UTC)))
        self.assertEqual(16, current_slot(datetime(2026, 9, 24, 13, 0, tzinfo=UTC)).hour)
        self.assertEqual(21, current_slot(datetime(2026, 9, 24, 18, 0, tzinfo=UTC)).hour)
        self.assertIsNone(current_slot(datetime(2026, 9, 24, 19, 0, tzinfo=UTC)))
        self.assertIsNone(current_slot(datetime(2026, 9, 25, 0, 0, tzinfo=UTC)))


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch.dict("os.environ", {"IDEA_RADAR_USER_ID": "100", "IDEA_RADAR_CHAT_ID": "100",
                                     "IDEA_RADAR_SOURCE": "codex", "IDEA_RADAR_ENABLED": "0"}):
            self.radar = IdeaRadar(NS(bot_data_dir=Path(self.tmp.name)), NS(client=None))
        self.radar.research = NS(generate=Mock(return_value=dict(idea=card(), reason="Хорошо", topics=["agents"])))
        self.bot = NS(send_message=AsyncMock(return_value=NS(message_id=15)))
        self.now = datetime(2026, 9, 24, 11, tzinfo=MSK)

    async def test_prepare_early_send_once_at_schedule(self):
        await self.radar.tick(self.bot, self.now.replace(hour=10, minute=45))
        self.bot.send_message.assert_not_awaited()
        await self.radar.tick(self.bot, self.now)
        await self.radar.tick(self.bot, self.now.replace(minute=1))
        self.bot.send_message.assert_awaited_once()
        self.radar.research.generate.assert_called_once()

    async def test_uncertain_delivery_never_replayed(self):
        self.bot.send_message.side_effect = TimeoutError()
        await self.radar.tick(self.bot, self.now)
        await self.radar.tick(self.bot, self.now.replace(minute=1))
        self.assertEqual("uncertain", self.radar.store.run(self.now.isoformat())["state"])
        self.bot.send_message.assert_awaited_once()

    async def test_failed_search_is_not_fake_card(self):
        self.radar.research.generate.side_effect = RuntimeError()
        await self.radar.tick(self.bot, self.now)
        self.assertEqual([], self.radar.store.recent())
        self.assertIn("технический пропуск", self.bot.send_message.call_args.kwargs["text"])

    async def test_pause_prevents_research_and_delivery(self):
        self.radar.store.setting("paused", "1")
        await self.radar.tick(self.bot, self.now)
        self.bot.send_message.assert_not_awaited()
        self.radar.research.generate.assert_not_called()

    async def test_interrupted_research_recovers_as_visible_failure(self):
        self.radar.store.claim(self.now.isoformat())
        await self.radar.tick(self.bot, self.now.replace(minute=11))
        self.bot.send_message.assert_awaited_once()
        self.radar.research.generate.assert_not_called()

    async def test_unauthorized_cannot_vote_or_spend(self):
        update = NS(effective_user=NS(id=999), effective_chat=NS(id=999, type="private"),
                    effective_message=NS(reply_text=AsyncMock()), callback_query=NS(data="radar:like:1"))
        await self.radar.callback(update, NS())
        self.assertEqual([], self.radar.store.memory()["feedback"])
        self.radar.research.generate.assert_not_called()

    async def test_reply_discussion_and_comment_memory(self):
        await self.radar.tick(self.bot, self.now)
        self.radar.research.discuss = Mock(return_value="Проверенный ответ")
        message = NS(text="Слишком большой капитал", reply_to_message=NS(message_id=15),
                     reply_text=AsyncMock(return_value=NS(message_id=16)))
        update = NS(effective_user=NS(id=100), effective_chat=NS(id=100, type="private"), message=message)
        self.assertTrue(await self.radar.handle_text(update, NS(user_data={})))
        self.assertEqual(2, len(self.radar.store.history(1)))
        self.assertEqual(1, self.radar.store.reply_card(16))
        self.assertIn("капитал", self.radar.store.memory()["user_comments"][0]["text"])

    async def test_telegram_buttons_fit_callback_limit(self):
        for row in card_keyboard(12345).inline_keyboard:
            for button in row:
                self.assertLessEqual(len(button.callback_data.encode()), 64)

    async def test_long_card_keeps_all_sources_in_document(self):
        c = card()
        c.update(id=1, fact="😀" * 420, hypothesis="😀" * 420, risks="😀" * 360,
                 test="😀" * 420, edge="😀" * 320)
        self.bot.send_document = AsyncMock(return_value=NS(message_id=17))
        await self.radar.send_card(self.bot, c)
        self.bot.send_message.assert_not_awaited()
        self.bot.send_document.assert_awaited_once()
        payload = self.bot.send_document.call_args.kwargs["document"].getvalue().decode()
        self.assertIn(c["sources"][1]["url"], payload)
        self.assertIn(c["kill"], payload)

    async def test_command_leaves_persistent_discussion(self):
        self.radar.store.setting("active_card", "1")
        update = NS(effective_user=NS(id=100), effective_chat=NS(id=100, type="private"))
        context = NS(user_data={"radar_card": 1})
        await self.radar.leave_on_command(update, context)
        self.assertEqual("", self.radar.store.setting("active_card"))
        self.assertNotIn("radar_card", context.user_data)

    async def test_codex_publish_keeps_telegram_feedback_and_deduplicates(self):
        urls = [source["url"] for source in card()["sources"]]
        report = dict(slot=self.now.isoformat(), idea=card(), reason="Подтверждено",
                      topics=["venture", "agents", "crypto"], consulted_urls=urls,
                      evidence="Оба конкретных документа проверены")
        session = AsyncMock()
        session.__aenter__.return_value = self.bot
        with patch("idea_manager_bot.radar_codex_bridge.Bot", return_value=session), \
             patch("idea_manager_bot.radar_codex_bridge.load_settings", return_value=NS(telegram_bot_token="fake")):
            self.assertEqual("sent", await codex_publish(self.radar, report, self.now))
            self.assertEqual("already_sent", await codex_publish(self.radar, report, self.now))
        self.bot.send_message.assert_awaited_once()
        self.assertEqual("sent", self.radar.store.run(self.now.isoformat())["state"])
        self.radar.store.vote(1, "topic", -1)
        snapshot = codex_context(self.radar, self.now)
        self.assertEqual(-1, snapshot["memory"]["feedback"][0]["value"])
        self.assertEqual(["venture", "agents", "ru_stocks"], snapshot["topics"][:3])
        self.assertIn("ru_stocks", snapshot["sources"])

    async def test_codex_queues_before_slot_and_bot_delivers_at_slot(self):
        urls = [source["url"] for source in card()["sources"]]
        report = dict(slot=self.now.isoformat(), idea=card(), reason="Подтверждено",
                      topics=["venture", "agents", "crypto"], consulted_urls=urls)
        with patch("idea_manager_bot.radar_codex_bridge.load_settings", return_value=NS(telegram_bot_token="fake")):
            self.assertEqual("queued", await codex_publish(self.radar, report, self.now.replace(hour=10, minute=45)))
        await self.radar.delivery_tick(self.bot, self.now.replace(hour=10, minute=59))
        self.bot.send_message.assert_not_awaited()
        await self.radar.delivery_tick(self.bot, self.now)
        await self.radar.delivery_tick(self.bot, self.now.replace(minute=1))
        self.bot.send_message.assert_awaited_once()
        self.assertEqual("sent", self.radar.store.run(self.now.isoformat())["state"])

    async def test_codex_publish_respects_pause_and_source_gate(self):
        report = dict(slot=self.now.isoformat(), idea=card(), reason="Подтверждено",
                      topics=["venture", "agents", "crypto"], consulted_urls=["https://example.com/other"])
        with self.assertRaisesRegex(ValueError, "Source was not returned"):
            await codex_publish(self.radar, report, self.now)
        self.radar.store.setting("paused", "1")
        with self.assertRaisesRegex(ValueError, "paused"):
            await codex_publish(self.radar, report, self.now)
        self.assertIsNone(self.radar.store.run(self.now.isoformat()))


if __name__ == "__main__":
    unittest.main()
