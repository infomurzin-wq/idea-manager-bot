from __future__ import annotations

import json
import os
import re
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

ESPN_CORE_EVENT_URL = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events/{event_id}?lang=en&region=us"
CORE_FALLBACK_HISTORY_LIMIT = int(os.environ.get("UFC_REPORTER_CORE_HISTORY_LIMIT", "0"))


def build_report_from_event_url(event_url: str) -> ReportSnapshot:
    try:
        event_page = fetch_text(event_url, cache_namespace="espn")
        event_data = extract_espn_payload(event_page, marker='"segMeta"')
        event = build_event_snapshot(event_url, event_data)
        report_version = "Stage 2 ESPN Direct"
    except Exception:
        event = build_event_snapshot_from_core_api(event_url)
        report_version = "Stage 2 ESPN Core API Fallback"
    event = enrich_event_with_fallback_card(event)
    event = enrich_event_with_opening_odds(event)
    event = enrich_event_with_totals(event)
    report = ReportSnapshot(
        event=event,
        generated_at=utc_timestamp(),
        report_version=report_version,
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


def build_event_snapshot_from_core_api(event_url: str) -> EventSnapshot:
    event_id = _event_id_from_url(event_url)
    payload = _fetch_core_json(ESPN_CORE_EVENT_URL.format(event_id=event_id))
    event_name = str(payload.get("name") or "UFC Event")
    event_date = _format_date(str(payload.get("date") or ""))
    venue = _core_event_location(payload)
    bouts = build_bouts_from_core_event(payload, event_date=event_date)
    quality_notes = [
        "Primary ESPN HTML недоступен, поэтому карточка собрана через ESPN Core API fallback.",
        "Moneyline и totals по-прежнему обогащаются внешними слоями, если они доступны.",
        "Предбоевые сигналы сохранены, но ESPN news scan может быть неполным из-за нестабильного HTML.",
    ]
    final_notes = [
        "Fallback включён автоматически: если ESPN fightcenter HTML пустой или без нужного payload, отчёт всё равно собирается из JSON API.",
        "Если часть last five не раскрылась через ESPN Core API, такие строки помечаются как `n/a`, а не ломают весь отчёт.",
    ]
    return EventSnapshot(
        event_id=slugify(f"{event_date}-{event_name}"),
        event_name=event_name,
        event_date=event_date,
        event_slug=slugify(event_name),
        event_url=event_url,
        source="espn_core_api_fallback",
        venue=venue,
        promotion="UFC",
        broadcast="n/a",
        confirmed_bouts=str(len(bouts)) if bouts else "n/a",
        primary_sources=[f"[ESPN fightcenter]({event_url})"],
        report_title_suffix="Stage 2 ESPN Core API Fallback",
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


def build_bouts_from_core_event(payload: dict[str, Any], *, event_date: str) -> list[BoutSnapshot]:
    competitions = payload.get("competitions")
    if not isinstance(competitions, list):
        return []

    bouts: list[BoutSnapshot] = []
    sorted_competitions = sorted(
        (item for item in competitions if isinstance(item, dict)),
        key=lambda item: _safe_int(item.get("matchNumber"), 999),
    )
    for index, competition in enumerate(sorted_competitions):
        competitors = competition.get("competitors")
        if not isinstance(competitors, list) or len(competitors) < 2:
            continue
        ordered_competitors = sorted(
            (item for item in competitors if isinstance(item, dict)),
            key=lambda item: _safe_int(item.get("order"), 999),
        )
        if len(ordered_competitors) < 2:
            continue
        weight_class = _core_weight_class(competition)
        fighter_a = build_fighter_from_core_competitor(
            ordered_competitors[0],
            event_weight_class=weight_class,
            event_date=event_date,
        )
        fighter_b = build_fighter_from_core_competitor(
            ordered_competitors[1],
            event_weight_class=weight_class,
            event_date=event_date,
        )
        card_segment = _core_card_segment(competition, index)
        bouts.append(
            BoutSnapshot(
                bout_id=str(competition.get("id") or slugify(f"{fighter_a.fighter_name}-{fighter_b.fighter_name}")),
                fighter_a_name=fighter_a.fighter_name,
                fighter_b_name=fighter_b.fighter_name,
                weight_class=weight_class,
                card_segment=card_segment,
                status=_core_bout_status(competition, card_segment, index),
                fighter_a_moneyline_decimal="n/a",
                fighter_b_moneyline_decimal="n/a",
                over_1_5_decimal="n/a",
                over_2_5_decimal="n/a",
                fighter_a=fighter_a,
                fighter_b=fighter_b,
                bout_commentary_ru=build_bout_commentary(fighter_a, fighter_b, weight_class),
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


def build_fighter_from_core_competitor(
    competitor: dict[str, Any],
    *,
    event_weight_class: str,
    event_date: str,
) -> FighterSnapshot:
    athlete_ref = _nested_ref(competitor, "athlete")
    athlete_payload = _fetch_core_json(athlete_ref) if athlete_ref else {}
    fighter_name = str(
        athlete_payload.get("displayName")
        or athlete_payload.get("fullName")
        or competitor.get("id")
        or "Unknown Fighter"
    )
    overview_url = _core_athlete_link(athlete_payload, "overview")
    history_url = _core_athlete_link(athlete_payload, "history")
    records_payload = _fetch_core_json(_nested_ref(athlete_payload, "records")) if _nested_ref(athlete_payload, "records") else {}
    summary = derive_summary_from_core_records(records_payload)
    last_five = build_last_five_from_core_eventlog(
        athlete_payload=athlete_payload,
        athlete_id=str(athlete_payload.get("id") or competitor.get("id") or ""),
    )
    if last_five:
        history_summary = derive_summary_from_history(
            [
                {
                    "rslt": _plain_result(entry.result),
                    "dcsn": entry.method,
                }
                for entry in last_five
            ],
            [],
        )
        if summary["wins_summary"] == "0 KO/TKO, 0 Submission, 0 Decision, 0 Other":
            summary["wins_summary"] = history_summary["wins_summary"]
        if summary["losses_summary"] == "0 KO/TKO, 0 Submission, 0 Decision, 0 Other":
            summary["losses_summary"] = history_summary["losses_summary"]
    sources = []
    if overview_url:
        sources.append(f"[ESPN profile]({overview_url})")
    if history_url:
        sources.append(f"[ESPN history]({history_url})")
    player_header = {
        "ath": {
            "wghtclss": _core_athlete_weight_class(athlete_payload),
        }
    }
    pre_fight_signals = build_pre_fight_signals(
        fighter_name=fighter_name,
        overview_url="",
        event_weight_class=event_weight_class,
        event_date=event_date,
        player_header=player_header,
        last_five=last_five,
    )
    return FighterSnapshot(
        fighter_slug=slugify(fighter_name),
        fighter_name=fighter_name,
        record_summary=summary["record_summary"],
        wins_summary=summary["wins_summary"],
        losses_summary=summary["losses_summary"],
        sources=sources,
        last_five=last_five,
        fighter_commentary_ru=build_fighter_commentary(fighter_name, last_five, summary),
        pre_fight_signals=pre_fight_signals,
        data_quality="partial",
    )


def build_last_five_from_core_eventlog(
    *,
    athlete_payload: dict[str, Any],
    athlete_id: str,
) -> list[FightResultEntry]:
    if CORE_FALLBACK_HISTORY_LIMIT <= 0:
        return []
    eventlog_ref = _nested_ref(athlete_payload, "eventLog")
    if not eventlog_ref:
        return []
    try:
        eventlog_payload = _fetch_core_json(eventlog_ref)
    except Exception:
        return []
    events = eventlog_payload.get("events", {})
    items = events.get("items", []) if isinstance(events, dict) else []
    last_five: list[FightResultEntry] = []
    for item in items:
        if len(last_five) >= CORE_FALLBACK_HISTORY_LIMIT:
            break
        if not isinstance(item, dict) or not item.get("played"):
            continue
        entry = _core_history_entry(item, athlete_id=athlete_id)
        if entry is not None:
            last_five.append(entry)
    return last_five


def _core_history_entry(item: dict[str, Any], *, athlete_id: str) -> FightResultEntry | None:
    try:
        event_payload = _fetch_core_json(_nested_ref(item, "event"))
        competition_payload = _fetch_core_json(_nested_ref(item, "competition"))
        status_payload = _fetch_core_json(_nested_ref(competition_payload, "status"))
    except Exception:
        return None
    event_name = str(event_payload.get("name") or "n/a")
    event_date = _format_date(str(event_payload.get("date") or competition_payload.get("date") or ""))
    opponent = _core_opponent_name(competition_payload, athlete_id=athlete_id)
    result = _core_result_for_athlete(competition_payload, athlete_id=athlete_id)
    status_result = status_payload.get("result", {})
    method = "n/a"
    if isinstance(status_result, dict):
        method = str(status_result.get("displayName") or status_result.get("shortDisplayName") or "n/a")
        detail = str(status_result.get("displayDescription") or status_result.get("description") or "").strip()
        if detail and detail.lower() != method.lower():
            method = f"{method} ({detail})"
    return FightResultEntry(
        fight_date=event_date,
        opponent=opponent,
        result=_result_marker(result),
        method=method,
        round=str(status_payload.get("period") or "n/a"),
        time=_core_finish_time(status_payload),
        promotion=_promotion_from_event_name(event_name),
        event_name=event_name,
    )


def _extract_history_url(side: dict[str, Any]) -> str:
    link = side.get("lnk", "")
    if "/fighter/" in link:
        return link.replace("/fighter/_/", "/fighter/history/_/")
    raise ValueError(f"Could not infer ESPN history URL from fighter link: {link}")


def derive_summary_from_core_records(payload: dict[str, Any]) -> dict[str, str]:
    record = {}
    items = payload.get("items", [])
    if isinstance(items, list) and items:
        first = items[0]
        record = first if isinstance(first, dict) else {}
    stats = record.get("stats", []) if isinstance(record, dict) else []
    stat_values = {
        str(item.get("name") or ""): int(float(item.get("value") or 0))
        for item in stats
        if isinstance(item, dict)
    }
    wins = {
        "KO/TKO": stat_values.get("tkos", 0),
        "Submission": stat_values.get("submissions", 0),
        "Decision": max(
            0,
            stat_values.get("wins", 0)
            - stat_values.get("tkos", 0)
            - stat_values.get("submissions", 0),
        ),
        "Other": 0,
    }
    losses = {
        "KO/TKO": stat_values.get("tkoLosses", 0),
        "Submission": stat_values.get("submissionLosses", 0),
        "Decision": max(
            0,
            stat_values.get("losses", 0)
            - stat_values.get("tkoLosses", 0)
            - stat_values.get("submissionLosses", 0),
        ),
        "Other": 0,
    }
    return {
        "record_summary": str(record.get("displayValue") or record.get("summary") or "n/a"),
        "wins_summary": _summary_string(wins),
        "losses_summary": _summary_string(losses),
    }


def _event_id_from_url(event_url: str) -> str:
    match = re.search(r"/id/(\d+)", event_url)
    if not match:
        raise ValueError(f"Could not infer ESPN event id from URL: {event_url}")
    return match.group(1)


def _fetch_core_json(url: str) -> dict[str, Any]:
    payload = fetch_text(_https_url(url), cache_namespace="espn-core")
    return json.loads(payload)


def _https_url(value: str) -> str:
    if value.startswith("http://"):
        return f"https://{value.removeprefix('http://')}"
    return value


def _nested_ref(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            return ref
    return ""


def _core_athlete_link(payload: dict[str, Any], rel_name: str) -> str:
    links = payload.get("links")
    if not isinstance(links, list):
        return ""
    for link in links:
        if not isinstance(link, dict):
            continue
        rel = link.get("rel")
        href = str(link.get("href") or "").strip()
        if isinstance(rel, list) and rel_name in rel and href.startswith("https://"):
            return href
    return ""


def _core_athlete_weight_class(payload: dict[str, Any]) -> str:
    weight_class = payload.get("weightClass")
    if isinstance(weight_class, dict):
        return str(weight_class.get("text") or weight_class.get("shortName") or "").strip()
    return ""


def _core_event_location(payload: dict[str, Any]) -> str:
    competitions = payload.get("competitions")
    if not isinstance(competitions, list):
        return "n/a"
    for competition in competitions:
        if not isinstance(competition, dict):
            continue
        venue = competition.get("venue")
        if not isinstance(venue, dict):
            continue
        full_name = str(venue.get("fullName") or "").strip()
        address = venue.get("address")
        address_parts: list[str] = []
        if isinstance(address, dict):
            for key in ("city", "state", "country"):
                value = str(address.get(key) or "").strip()
                if value:
                    address_parts.append(value)
        if full_name and address_parts:
            return f"{full_name}, {', '.join(address_parts)}"
        if full_name:
            return full_name
    return "n/a"


def _core_weight_class(competition: dict[str, Any]) -> str:
    payload = competition.get("type")
    if isinstance(payload, dict):
        return str(payload.get("text") or payload.get("abbreviation") or "n/a")
    return "n/a"


def _core_card_segment(competition: dict[str, Any], index: int) -> str:
    payload = competition.get("cardSegment")
    if isinstance(payload, dict):
        description = str(payload.get("description") or "").strip()
        if description:
            return _normalize_segment_name(description, index)
    return "Main Event" if index == 0 else "Card"


def _core_bout_status(competition: dict[str, Any], card_segment: str, index: int) -> str:
    fmt = competition.get("format")
    if isinstance(fmt, dict):
        regulation = fmt.get("regulation")
        if isinstance(regulation, dict):
            periods = regulation.get("periods")
            if periods:
                return f"{periods} x 5"
    return "5 x 5" if card_segment == "Main Event" or index == 0 else "3 x 5"


def _core_opponent_name(competition: dict[str, Any], *, athlete_id: str) -> str:
    competitors = competition.get("competitors")
    if not isinstance(competitors, list):
        return "n/a"
    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        if str(competitor.get("id") or "") == athlete_id:
            continue
        athlete_ref = _nested_ref(competitor, "athlete")
        if not athlete_ref:
            continue
        try:
            athlete = _fetch_core_json(athlete_ref)
        except Exception:
            continue
        return str(athlete.get("displayName") or athlete.get("fullName") or competitor.get("id") or "n/a")
    return "n/a"


def _core_result_for_athlete(competition: dict[str, Any], *, athlete_id: str) -> str:
    competitors = competition.get("competitors")
    if not isinstance(competitors, list):
        return "n/a"
    athlete_competitor = None
    winner_seen = False
    for competitor in competitors:
        if not isinstance(competitor, dict):
            continue
        if competitor.get("winner") is True:
            winner_seen = True
        if str(competitor.get("id") or "") == athlete_id:
            athlete_competitor = competitor
    if athlete_competitor is None:
        return "n/a"
    if athlete_competitor.get("winner") is True:
        return "W"
    if winner_seen:
        return "L"
    return "D"


def _core_finish_time(status_payload: dict[str, Any]) -> str:
    clock = status_payload.get("clock")
    try:
        remaining = float(clock)
    except (TypeError, ValueError):
        return str(status_payload.get("displayClock") or "n/a")
    if remaining < 0 or remaining > 300:
        return str(status_payload.get("displayClock") or "n/a")
    elapsed = int(300 - remaining)
    return f"{elapsed // 60}:{elapsed % 60:02d}"


def _plain_result(value: str) -> str:
    if "W" in value:
        return "W"
    if "L" in value:
        return "L"
    if "D" in value:
        return "D"
    if "NC" in value:
        return "NC"
    return value


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


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
    if not last_five:
        return (
            f"По {fighter_name} fallback-сборщик сейчас даёт агрегированный record и методы, "
            "но last-five не загружен, чтобы не блокировать автоматический cron."
        )
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
