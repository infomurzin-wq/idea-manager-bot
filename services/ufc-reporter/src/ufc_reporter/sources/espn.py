from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from lxml import html as lxml_html

from ..models import (
    BoutSnapshot,
    EventSnapshot,
    FighterSnapshot,
    FightResultEntry,
    PreFightSignal,
    ReportSnapshot,
)
from ..normalize import compute_content_hash, report_payload_for_hash, slugify, utc_timestamp
from .http import fetch_text
from .mmaoddsbreaker import enrich_event_with_opening_odds
from .polymarket import enrich_event_with_totals
from .signals import build_pre_fight_signals
from .ufc_official import enrich_event_with_fallback_card


def build_report_from_event_url(event_url: str) -> ReportSnapshot:
    event_page = fetch_text(event_url, cache_namespace="espn")
    event_data = extract_espn_payload(event_page, marker='"segMeta"')
    event = build_event_snapshot(event_url, event_data)
    event = enrich_event_with_fallback_card(event)
    event = enrich_event_with_opening_odds(event)
    event = enrich_event_with_totals(event)
    report = ReportSnapshot(
        event=event,
        generated_at=utc_timestamp(),
        report_version="Stage 2 ESPN Direct",
        content_hash="pending",
        source_report_path=event_url,
    )
    report.content_hash = compute_content_hash(report_payload_for_hash(report.to_dict()))
    return report


def extract_espn_payload(page_html: str, *, marker: str) -> dict[str, Any]:
    document = lxml_html.fromstring(page_html)
    scripts = document.xpath("//script/text()")
    for script_text in scripts:
        if marker not in script_text:
            continue
        candidate = _extract_json_candidate(script_text, marker=marker)
        if candidate:
            return candidate
    raise ValueError(f"Could not find ESPN payload marker: {marker}")


def _extract_json_candidate(script_text: str, *, marker: str) -> dict[str, Any] | None:
    marker_index = script_text.find(marker)
    if marker_index == -1:
        return None
    anchor = script_text.rfind('"page":{', 0, marker_index)
    search_from = anchor if anchor != -1 else marker_index
    start = script_text.rfind("{", 0, search_from)
    while start != -1:
        candidate = _balanced_json_from(script_text, start)
        if candidate and marker in candidate:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        start = script_text.rfind("{", 0, start)
    return None


def _balanced_json_from(script_text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(script_text)):
        char = script_text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return script_text[start : index + 1]
    return None


def build_event_snapshot(event_url: str, payload: dict[str, Any]) -> EventSnapshot:
    game_info = payload.get("page", {}).get("content", {}).get("gamepackage", {})
    header = game_info.get("hdr", {})
    event_meta = header.get("evt", {})
    venue_meta = header.get("venue", {})
    event_name = event_meta.get("nm", "UFC Event")
    event_date = _format_date(event_meta.get("dt"))
    venue = _format_venue(venue_meta)
    broadcast = _extract_network(game_info)
    segments = game_info.get("cardSegs", [])
    bouts = build_bouts(segments)
    confirmed_bouts = str(len(bouts)) if bouts else "n/a"
    quality_notes = [
        "Moneyline: ESPN payload сам по себе не даёт стабильных линий, поэтому для коэффициентов нужен внешний enrichment layer.",
        "`ТБ 1.5` / `ТБ 2.5`: ESPN event page сам по себе не даёт stable totals lines, поэтому для них нужен отдельный источник.",
        "Предбоевые сигналы: теперь собираются из deterministic context и осторожного ESPN news scan, но coverage по внешним новостям всё ещё неполный.",
        "Общая оценка качества: `partial`, потому что Stage 2 direct-source builder всё ещё опирается на ESPN как primary card source, а odds/news layer пока неполный.",
    ]
    final_notes = [
        "Это первый direct-source вариант Stage 2: event card и fight history собираются напрямую из ESPN page payload.",
        "Следующий слой для улучшения: totals enrichment, fallback-источники и более сильный news/search layer.",
    ]
    return EventSnapshot(
        event_id=slugify(f"{event_date}-{event_name}"),
        event_name=event_name,
        event_date=event_date,
        event_slug=slugify(event_name),
        event_url=event_url,
        source="espn_direct",
        venue=venue,
        promotion="UFC",
        broadcast=broadcast,
        confirmed_bouts=confirmed_bouts,
        primary_sources=[f"[ESPN fightcenter]({event_url})"],
        report_title_suffix="Stage 2 ESPN Direct",
        report_format="full-card detailed",
        language="русский",
        odds_format="decimal only",
        quality_label="partial",
        quality_notes=quality_notes,
        final_notes=final_notes,
        bouts=bouts,
    )


def build_bouts(segments: list[dict[str, Any]]) -> list[BoutSnapshot]:
    bouts: list[BoutSnapshot] = []
    for segment in segments:
        segment_name = segment.get("hdr", "Card")
        matches = segment.get("mtchs", [])
        for index, match in enumerate(matches):
            away = match.get("awy", {})
            home = match.get("hme", {})
            event_weight_class = match.get("nte", "n/a")
            event_date = _format_date(match.get("dt"))
            fighter_a = build_fighter_from_match_side(
                away,
                event_weight_class=event_weight_class,
                event_date=event_date,
            )
            fighter_b = build_fighter_from_match_side(
                home,
                event_weight_class=event_weight_class,
                event_date=event_date,
            )
            status = "5 x 5" if segment.get("nm") == "main" and index == 0 else "3 x 5"
            bouts.append(
                BoutSnapshot(
                    bout_id=str(match.get("id", slugify(f"{fighter_a.fighter_name}-{fighter_b.fighter_name}"))),
                    fighter_a_name=fighter_a.fighter_name,
                    fighter_b_name=fighter_b.fighter_name,
                    weight_class=event_weight_class,
                    card_segment=_normalize_segment_name(segment_name, index),
                    status=status,
                    fighter_a_moneyline_decimal="n/a",
                    fighter_b_moneyline_decimal="n/a",
                    over_1_5_decimal="n/a",
                    over_2_5_decimal="n/a",
                    fighter_a=fighter_a,
                    fighter_b=fighter_b,
                    bout_commentary_ru=build_bout_commentary(fighter_a, fighter_b, match.get("nte", "n/a")),
                )
            )
    return bouts


def build_fighter_from_match_side(
    side: dict[str, Any],
    *,
    event_weight_class: str,
    event_date: str,
) -> FighterSnapshot:
    fighter_name = side.get("dspNm", "Unknown Fighter")
    history_url = _extract_history_url(side)
    history_page = fetch_text(history_url, cache_namespace="espn")
    history_payload = extract_espn_payload(history_page, marker='"fghtHstr"')
    history_entries = history_payload.get("page", {}).get("content", {}).get("player", {}).get("fghtHstr", [])
    player_header = history_payload.get("page", {}).get("content", {}).get("player", {}).get("plyrHdr", {})
    stats_block = player_header.get("statsBlck", {}).get("vals", [])
    last_five = [convert_history_entry(entry) for entry in history_entries[:5]]
    summary = derive_summary_from_history(history_entries, stats_block)
    record_summary = summary["record_summary"] or side.get("rec", "n/a")
    sources = [f"[ESPN history]({history_url})"]
    overview_url = side.get("lnk")
    if overview_url:
        sources.insert(0, f"[ESPN profile]({overview_url})")
    pre_fight_signals = build_pre_fight_signals(
        fighter_name=fighter_name,
        overview_url=overview_url or "",
        event_weight_class=event_weight_class,
        event_date=event_date,
        player_header=player_header,
        last_five=last_five,
    )
    return FighterSnapshot(
        fighter_slug=slugify(fighter_name),
        fighter_name=fighter_name,
        record_summary=record_summary,
        wins_summary=summary["wins_summary"],
        losses_summary=summary["losses_summary"],
        sources=sources,
        last_five=last_five,
        fighter_commentary_ru=build_fighter_commentary(fighter_name, last_five, summary),
        pre_fight_signals=pre_fight_signals,
        data_quality="partial",
    )


def _extract_history_url(side: dict[str, Any]) -> str:
    link = side.get("lnk", "")
    if "/fighter/" in link:
        return link.replace("/fighter/_/", "/fighter/history/_/")
    raise ValueError(f"Could not infer ESPN history URL from fighter link: {link}")


def convert_history_entry(entry: dict[str, Any]) -> FightResultEntry:
    return FightResultEntry(
        fight_date=_format_date(entry.get("hdate")),
        opponent=entry.get("opp", "n/a"),
        result=_result_marker(entry.get("rslt", "n/a")),
        method=entry.get("dcsn", "n/a"),
        round=str(entry.get("rnd", "n/a")),
        time=str(entry.get("htime", "n/a")),
        promotion=_promotion_from_event_name(entry.get("evnt", "n/a")),
        event_name=entry.get("evnt", "n/a"),
    )


def derive_summary_from_history(history_entries: list[dict[str, Any]], stats_block: list[dict[str, Any]]) -> dict[str, str]:
    wins_total = 0
    losses_total = 0
    draws_total = 0
    wins = {"KO/TKO": 0, "Submission": 0, "Decision": 0, "Other": 0}
    losses = {"KO/TKO": 0, "Submission": 0, "Decision": 0, "Other": 0}
    for entry in history_entries:
        result = entry.get("rslt")
        method_bucket = _method_bucket(entry.get("dcsn", ""))
        if result == "W":
            wins_total += 1
            wins[method_bucket] += 1
        elif result == "L":
            losses_total += 1
            losses[method_bucket] += 1
        elif result == "D":
            draws_total += 1
    record_summary = _extract_record_from_stats(stats_block)
    if not record_summary:
        record_summary = f"{wins_total}-{losses_total}-{draws_total}"
    return {
        "record_summary": record_summary,
        "wins_summary": _summary_string(wins),
        "losses_summary": _summary_string(losses),
    }


def _extract_record_from_stats(stats_block: list[dict[str, Any]]) -> str:
    for row in stats_block:
        if row.get("lbl") == "W-L-D":
            return row.get("val", "")
    return ""


def _summary_string(payload: dict[str, int]) -> str:
    return ", ".join(
        [
            f"{payload['KO/TKO']} KO/TKO",
            f"{payload['Submission']} Submission",
            f"{payload['Decision']} Decision",
            f"{payload['Other']} Other",
        ]
    )


def _method_bucket(method: str) -> str:
    lowered = method.lower()
    if "ko" in lowered or lowered == "tko":
        return "KO/TKO"
    if "submission" in lowered or lowered.startswith("sub"):
        return "Submission"
    if "decision" in lowered or lowered == "draw":
        return "Decision"
    return "Other"


def _normalize_segment_name(segment_name: str, index: int) -> str:
    lowered = segment_name.lower()
    if "main" in lowered and index == 0:
        return "Main Event"
    if "main" in lowered and index == 1:
        return "Co-Main"
    if "main" in lowered:
        return "Main Card"
    if "prelim" in lowered:
        return "Prelim"
    return segment_name


def _extract_network(game_info: dict[str, Any]) -> str:
    segments = game_info.get("segMeta", {})
    for key in ("main", "prelims1"):
        name = segments.get(key, {}).get("ntwk", {}).get("nm")
        if name:
            return name
    return "n/a"


def _format_venue(venue_meta: dict[str, Any]) -> str:
    location = venue_meta.get("loc", "n/a")
    address = venue_meta.get("locAddr", {})
    city = address.get("city")
    state = address.get("state")
    country = address.get("country")
    trailing = ", ".join(part for part in (city, state, country) if part)
    if trailing and location != "n/a":
        return f"{location}, {trailing}"
    return location


def _format_date(value: str | None) -> str:
    if not value:
        return "n/a"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()


def _promotion_from_event_name(event_name: str) -> str:
    if event_name.startswith("UFC"):
        return "UFC"
    if event_name.startswith("DWCS"):
        return "DWCS"
    if event_name.startswith("LFA"):
        return "LFA"
    if event_name.startswith("PFL"):
        return "PFL"
    if event_name.startswith("Bellator"):
        return "Bellator"
    return event_name.split(":", 1)[0] if ":" in event_name else event_name


def _result_marker(result: str) -> str:
    mapping = {
        "W": "🟩 W",
        "L": "🟥 L",
        "D": "🟨 D",
        "NC": "⬜ NC",
    }
    return mapping.get(result, result)


def build_fighter_commentary(
    fighter_name: str,
    last_five: list[FightResultEntry],
    summary: dict[str, str],
) -> str:
    wins = sum(1 for fight in last_five if fight.result == "🟩 W")
    finish_wins = sum(
        1
        for fight in last_five
        if fight.result == "🟩 W"
        and (fight.method in {"KO/TKO", "TKO"} or "Submission" in fight.method)
    )
    if wins >= 4 and finish_wins >= 3:
        return f"У {fighter_name} сейчас очень сильная серия и выраженный финишный профиль по свежему отрезку."
    if wins >= 4:
        return f"У {fighter_name} свежая форма выглядит устойчиво: по последним пяти боям это сильный положительный отрезок."
    if wins <= 2:
        return f"У {fighter_name} по последним пяти боям форма выглядит нестабильно, и это важно учитывать до рынка."
    if "0 Submission" in summary["losses_summary"]:
        return f"Профиль {fighter_name} выглядит достаточно устойчивым против сабмишн-риска, но общий сценарий боя всё равно нужно читать через стиль соперника."
    return f"Профиль {fighter_name} по последним пяти боям смешанный: здесь важно не только raw record, но и способ побед и поражений."


def build_bout_commentary(
    fighter_a: FighterSnapshot,
    fighter_b: FighterSnapshot,
    weight_class: str,
) -> str:
    a_wins = sum(1 for fight in fighter_a.last_five if fight.result == "🟩 W")
    b_wins = sum(1 for fight in fighter_b.last_five if fight.result == "🟩 W")
    if a_wins > b_wins:
        edge = fighter_a.fighter_name
    elif b_wins > a_wins:
        edge = fighter_b.fighter_name
    else:
        edge = "никто явно"
    if edge == "никто явно":
        return f"По свежей форме в паре {fighter_a.fighter_name} vs. {fighter_b.fighter_name} нет явного перевеса; бой в {weight_class} лучше читать через стиль, а не только через цифру record."
    return f"По свежей форме небольшой перевес сейчас у {edge}, но для боя в {weight_class} этого недостаточно без дополнительного odds/news слоя."
