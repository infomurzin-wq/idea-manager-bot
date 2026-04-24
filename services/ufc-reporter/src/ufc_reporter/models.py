from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class FightResultEntry:
    fight_date: str
    opponent: str
    result: str
    method: str
    round: str
    promotion: str
    event_name: str
    time: str = "n/a"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FightResultEntry":
        return cls(**payload)


@dataclass
class PreFightSignal:
    summary_ru: str
    source: str = "n/a"
    signal_type: str = "context"
    impact_note_ru: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PreFightSignal":
        return cls(**payload)


@dataclass
class FighterSnapshot:
    fighter_slug: str
    fighter_name: str
    record_summary: str
    wins_summary: str
    losses_summary: str
    sources: list[str] = field(default_factory=list)
    last_five: list[FightResultEntry] = field(default_factory=list)
    fighter_commentary_ru: str = ""
    pre_fight_signals: list[PreFightSignal] = field(default_factory=list)
    data_quality: str = "good"
    additional_notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FighterSnapshot":
        return cls(
            fighter_slug=payload["fighter_slug"],
            fighter_name=payload["fighter_name"],
            record_summary=payload["record_summary"],
            wins_summary=payload["wins_summary"],
            losses_summary=payload["losses_summary"],
            sources=list(payload.get("sources", [])),
            last_five=[
                FightResultEntry.from_dict(item)
                for item in payload.get("last_five", [])
            ],
            fighter_commentary_ru=payload.get("fighter_commentary_ru", ""),
            pre_fight_signals=[
                PreFightSignal.from_dict(item)
                for item in payload.get("pre_fight_signals", [])
            ],
            data_quality=payload.get("data_quality", "good"),
            additional_notes=list(payload.get("additional_notes", [])),
        )


@dataclass
class BoutSnapshot:
    bout_id: str
    fighter_a_name: str
    fighter_b_name: str
    weight_class: str
    card_segment: str
    status: str
    fighter_a_moneyline_decimal: str = "n/a"
    fighter_b_moneyline_decimal: str = "n/a"
    over_1_5_decimal: str = "n/a"
    over_2_5_decimal: str = "n/a"
    fighter_a: FighterSnapshot | None = None
    fighter_b: FighterSnapshot | None = None
    bout_commentary_ru: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BoutSnapshot":
        return cls(
            bout_id=payload["bout_id"],
            fighter_a_name=payload["fighter_a_name"],
            fighter_b_name=payload["fighter_b_name"],
            weight_class=payload.get("weight_class", "n/a"),
            card_segment=payload.get("card_segment", "n/a"),
            status=payload.get("status", "n/a"),
            fighter_a_moneyline_decimal=payload.get(
                "fighter_a_moneyline_decimal", "n/a"
            ),
            fighter_b_moneyline_decimal=payload.get(
                "fighter_b_moneyline_decimal", "n/a"
            ),
            over_1_5_decimal=payload.get("over_1_5_decimal", "n/a"),
            over_2_5_decimal=payload.get("over_2_5_decimal", "n/a"),
            fighter_a=(
                FighterSnapshot.from_dict(payload["fighter_a"])
                if payload.get("fighter_a")
                else None
            ),
            fighter_b=(
                FighterSnapshot.from_dict(payload["fighter_b"])
                if payload.get("fighter_b")
                else None
            ),
            bout_commentary_ru=payload.get("bout_commentary_ru", ""),
        )


@dataclass
class EventSnapshot:
    event_id: str
    event_name: str
    event_date: str
    event_slug: str
    event_url: str = "n/a"
    source: str = "manual_import"
    venue: str = "n/a"
    promotion: str = "n/a"
    broadcast: str = "n/a"
    confirmed_bouts: str = "n/a"
    primary_sources: list[str] = field(default_factory=list)
    report_title_suffix: str = "Stage 2 Report"
    report_format: str = "full-card detailed"
    language: str = "русский"
    odds_format: str = "decimal only"
    quality_label: str = "partial"
    quality_notes: list[str] = field(default_factory=list)
    final_notes: list[str] = field(default_factory=list)
    bouts: list[BoutSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EventSnapshot":
        return cls(
            event_id=payload["event_id"],
            event_name=payload["event_name"],
            event_date=payload["event_date"],
            event_slug=payload["event_slug"],
            event_url=payload.get("event_url", "n/a"),
            source=payload.get("source", "manual_import"),
            venue=payload.get("venue", "n/a"),
            promotion=payload.get("promotion", "n/a"),
            broadcast=payload.get("broadcast", "n/a"),
            confirmed_bouts=payload.get("confirmed_bouts", "n/a"),
            primary_sources=list(payload.get("primary_sources", [])),
            report_title_suffix=payload.get(
                "report_title_suffix", "Stage 2 Report"
            ),
            report_format=payload.get("report_format", "full-card detailed"),
            language=payload.get("language", "русский"),
            odds_format=payload.get("odds_format", "decimal only"),
            quality_label=payload.get("quality_label", "partial"),
            quality_notes=list(payload.get("quality_notes", [])),
            final_notes=list(payload.get("final_notes", [])),
            bouts=[
                BoutSnapshot.from_dict(item) for item in payload.get("bouts", [])
            ],
        )


@dataclass
class ReportSnapshot:
    event: EventSnapshot
    generated_at: str
    report_version: str
    content_hash: str
    source_report_path: str = "n/a"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReportSnapshot":
        return cls(
            event=EventSnapshot.from_dict(payload["event"]),
            generated_at=payload["generated_at"],
            report_version=payload["report_version"],
            content_hash=payload["content_hash"],
            source_report_path=payload.get("source_report_path", "n/a"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

