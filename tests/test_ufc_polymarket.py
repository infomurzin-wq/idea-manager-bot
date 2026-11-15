import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from idea_manager_bot.ufc_polymarket import UfcPolymarket
from ufc_reporter.models import BoutSnapshot, EventSnapshot, FighterSnapshot
from ufc_reporter.polymarket_singles import discover_singles, resolved_payout_factor


class UfcPolymarketTest(unittest.TestCase):
    def test_discovery_uses_ask_and_exact_threshold(self):
        event = EventSnapshot(
            event_id="1", event_name="UFC 999", event_date="2026-11-21", event_slug="ufc-999",
            bouts=[BoutSnapshot("b1", "A Fighter", "B Fighter", "Lightweight", "main", "scheduled")],
        )
        gamma = [{
            "title": "UFC 999: A Fighter vs. B Fighter",
            "markets": [{
                "id": "42", "question": "O/U 1.5 Rounds", "active": True,
                "closed": False, "acceptingOrders": True,
                "outcomes": '["Over","Under"]', "clobTokenIds": '["11","22"]',
            }],
        }]
        books = {
            "11": {"asks": [{"price": "0.59"}]},
            "22": {"asks": [{"price": "0.588"}, {"price": "0.60"}]},
        }
        with patch("ufc_reporter.polymarket_singles._fetch_gamma_events", return_value=gamma), patch(
            "ufc_reporter.polymarket_singles._books", return_value=books
        ):
            singles = discover_singles(event)
        self.assertEqual([item["outcome"] for item in singles], ["Under"])
        self.assertEqual(singles[0]["decimal"], "1.7007")

    def test_selection_is_idempotent_and_bank_is_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = UfcPolymarket(Path(tmp))
            item = {
                "bout": "A — B", "question": "Winner", "outcome": "A", "decimal": "2.0000",
                "ask": "0.5", "captured_at": "2026-11-20T10:00:00+00:00",
                "market_id": "42", "token_id": "11",
            }
            with store._connect() as db:
                db.execute(
                    "INSERT INTO candidates (id,token_id,event_slug,event_name,event_date,payload,card) "
                    "VALUES (1,'11','e','UFC 999','2026-11-21',?, 'card')",
                    (json.dumps(item),),
                )
            with patch("ufc_reporter.polymarket_singles._json_request", return_value={"closed": False, "acceptingOrders": True}):
                store._decide(1, 7, "selected")
                store._decide(1, 7, "selected")
            with store._connect() as db:
                self.assertEqual(store._free_bank(db, 7), 290000)
                self.assertEqual(store._free_bank(db, 8), 300000)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 1)
            with patch("ufc_reporter.polymarket_singles.resolved_payout_factor", return_value=1):
                stats = store._stats(7)
            self.assertIn("+100,00%", stats["text"])
            self.assertIn("310 000,00", stats["text"])

    def test_only_final_market_prices_settle(self):
        market = {
            "closed": True, "acceptingOrders": False,
            "clobTokenIds": '["11","22"]', "outcomePrices": '["0.5","0.5"]',
        }
        with patch("ufc_reporter.polymarket_singles._json_request", return_value=market):
            self.assertEqual(resolved_payout_factor("42", "11"), 0.5)
        market["outcomePrices"] = '["0.98","0.02"]'
        with patch("ufc_reporter.polymarket_singles._json_request", return_value=market):
            self.assertIsNone(resolved_payout_factor("42", "11"))

    def test_thursday_document_import_preserves_quote_and_fighter_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = UfcPolymarket(Path(tmp))
            fighter = FighterSnapshot("a", "A Fighter", "10-2", "KO 5", "SUB 1")
            event = EventSnapshot(
                event_id="1", event_name="UFC 999", event_date="2026-11-21", event_slug="ufc-999",
                bouts=[BoutSnapshot("b1", "A Fighter", "B Fighter", "Lightweight", "main", "scheduled", fighter_a=fighter)],
            )
            from dataclasses import asdict

            item = {
                "event_slug": "ufc-999", "bout_id": "b1", "bout": "A Fighter — B Fighter",
                "question": "Winner", "outcome": "A Fighter", "decimal": "2.0000",
                "ask": "0.5", "captured_at": "2026-11-20T10:00:00+00:00",
                "market_id": "42", "token_id": "11",
            }
            raw = json.dumps({"event": asdict(event), "singles": [item]}).encode()
            with patch.object(store, "_refresh_if_needed", return_value={"event_slug": "ufc-999", "event_name": "UFC 999", "count": 1}):
                screen = store.import_catalogue(raw, 7)
            self.assertIn("1 исходов", screen["text"])
            self.assertIn("Победы: KO 5", store._show(1, 7)["text"])


if __name__ == "__main__":
    unittest.main()
