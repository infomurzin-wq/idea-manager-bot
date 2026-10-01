import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from ufc_reporter import monitoring
from ufc_reporter.models import BoutSnapshot, EventSnapshot, ReportSnapshot
from ufc_reporter.sources import espn, ufc_official


def bout(a: str, b: str) -> BoutSnapshot:
    return BoutSnapshot(
        bout_id=f"{a}-{b}", fighter_a_name=a, fighter_b_name=b,
        weight_class="n/a", card_segment="n/a", status="n/a",
    )


def event() -> EventSnapshot:
    return EventSnapshot(
        event_id="ufc-332", event_name="UFC 332: Silva vs. Wang",
        event_date="2026-10-03", event_slug="ufc-332-silva-vs-wang",
        bouts=[bout("Natalia Silva", "Wang Cong")],
    )


class CardSafetyTests(unittest.TestCase):
    def test_numbered_event_uses_exact_ufc_page(self):
        index = (
            '<a href="/event/ufc-fight-night-september-12-2026">Silva vs Delgado</a>'
            '<a href="/event/ufc-332">Silva vs Wang</a>'
        )
        with patch.object(ufc_official, "fetch_text", return_value=index):
            self.assertEqual(
                ufc_official.discover_event_url(event()), "https://www.ufc.com/event/ufc-332"
            )

    def test_unrelated_card_cannot_be_merged(self):
        report_event = event()
        with patch.object(ufc_official, "discover_event_url", return_value="https://www.ufc.com/event/wrong"), patch.object(
            ufc_official, "fetch_text", return_value="<html/>"
        ), patch.object(
            ufc_official, "parse_event_card", return_value=[bout("Jean Silva", "Jose Miguel Delgado")]
        ):
            ufc_official.enrich_event_with_fallback_card(report_event)
        self.assertEqual(len(report_event.bouts), 1)
        self.assertNotIn("ufc_official_fallback", report_event.source)

    def test_one_shared_bout_does_not_validate_another_card(self):
        report_event = event()
        report_event.bouts.extend([bout("A B", "C D"), bout("E F", "G H")])
        other_card = [report_event.bouts[0], bout("Jean Silva", "Jose Miguel Delgado"), bout("J K", "L M")]
        with patch.object(ufc_official, "discover_event_url", return_value="https://www.ufc.com/event/wrong"), patch.object(
            ufc_official, "fetch_text", return_value="<html/>"
        ), patch.object(ufc_official, "parse_event_card", return_value=other_card):
            ufc_official.enrich_event_with_fallback_card(report_event)
        self.assertEqual(len(report_event.bouts), 3)

    def test_missing_fight_history_blocks_report(self):
        with patch.object(espn, "fetch_text", side_effect=ValueError("empty HTML")), patch.object(
            espn, "build_event_snapshot_from_core_api", return_value=event()
        ), patch.object(espn, "enrich_event_with_fallback_card", side_effect=lambda value: value), patch.object(
            espn, "enrich_event_with_opening_odds", side_effect=AssertionError("should not enrich")
        ):
            with self.assertRaisesRegex(ValueError, "missing fight history"):
                espn.build_report_from_event_url("https://www.espn.com/mma/fightcenter/_/id/600061182/league/ufc")

    def test_search_chooses_official_nickname_over_event_weight(self):
        search = {"results": [{"type": "player", "contents": [
            {"sport": "mma", "displayName": "Anthony Romero", "link": {"web": "https://www.espn.com/mma/fighter/_/id/4684470/anthony-romero"}},
            {"sport": "mma", "displayName": "Anthony Romero", "link": {"web": "https://www.espn.com/mma/fighter/_/id/5454993/anthony-romero"}},
        ]}]}
        with patch.object(espn, "fetch_text", side_effect=[
            json.dumps(search), '<p class="hero-profile__nickname">"The Bully"</p>'
        ]), patch.object(
            espn, "_fetch_core_json", side_effect=[
                {"nickname": "The Genius", "weightClass": {"text": "Featherweight"}},
                {"nickname": "The Bully", "weightClass": {"text": "Bantamweight"}},
            ]
        ), patch.object(espn, "build_fighter_from_core_competitor") as build:
            espn.find_fighter_from_core_search(
                "Anthony Romero", event_weight_class="Featherweight", event_date="2026-10-03",
                official_profile_url="https://www.ufc.com/athlete/anthony-romero-0",
            )
        self.assertIn("/5454993?", build.call_args.args[0]["athlete"]["$ref"])

    def test_incremental_replaces_incomplete_previous_report(self):
        report = ReportSnapshot(event=event(), generated_at="now", report_version="test", content_hash="new")
        old_report = ReportSnapshot(event=event(), generated_at="old", report_version="test", content_hash="old")
        send = Mock()
        update = Mock()
        with patch.multiple(
            monitoring,
            load_active_weekend_event=Mock(return_value={"event_date": "2026-10-03", "event_url": "event-url"}),
            _event_is_still_in_weekend_window=Mock(return_value=True),
            build_report_from_event_url=Mock(return_value=report),
            load_last_sent_report=Mock(return_value={"last_meaningful_hash": "old"}),
            load_sent_snapshot=Mock(return_value=old_report),
            _persist_report=Mock(return_value=(Path("snapshot.json"), Path("report.md"))),
            _meaningful_hash=Mock(return_value="new"),
            _send_if_requested=send,
            update_sent_report_state=update,
        ):
            result = monitoring._run_incremental(
                current_date=date(2026, 10, 2), send="telegram", weekend_only=True
            )
        self.assertEqual(result.status, "corrected")
        self.assertEqual(send.call_args.kwargs["report_kind"], "corrected")
        self.assertEqual(update.call_args.kwargs["report_kind"], "corrected")


if __name__ == "__main__":
    unittest.main()
