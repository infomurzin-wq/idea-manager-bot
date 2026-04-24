from __future__ import annotations

import json
import re
from typing import Any

from .http import fetch_text
from ..models import EventSnapshot
from ..normalize import fighter_name_score

UFC_INDEX_URL = "https://polymarket.com/sports/ufc"


def enrich_event_with_totals(event: EventSnapshot) -> EventSnapshot:
    payload = fetch_text(UFC_INDEX_URL, cache_namespace="polymarket")
    next_data = _extract_next_data(payload)
    events = _extract_index_events(next_data)
    matched = 0
    for bout in event.bouts:
        market_event = _match_event_for_bout(bout.fighter_a_name, bout.fighter_b_name, events)
        if not market_event:
            continue
        over_1_5 = _extract_over_decimal(market_event, "O/U 1.5 Rounds")
        over_2_5 = _extract_over_decimal(market_event, "O/U 2.5 Rounds")
        if over_1_5 != "n/a":
            bout.over_1_5_decimal = over_1_5
        if over_2_5 != "n/a":
            bout.over_2_5_decimal = over_2_5
        if over_1_5 != "n/a" or over_2_5 != "n/a":
            matched += 1

    if matched:
        source_link = f"[Polymarket UFC index]({UFC_INDEX_URL})"
        if source_link not in event.primary_sources:
            event.primary_sources.append(source_link)
        if "polymarket_totals" not in event.source:
            event.source = f"{event.source} + polymarket_totals"
        event.quality_notes.append(
            f"`ТБ 1.5` / `ТБ 2.5`: totals markets сматчены для {matched}/{len(event.bouts)} боёв через Polymarket."
        )
        event.quality_notes.append(
            "Важно: totals здесь не sportsbook lines, а market-implied decimal odds из Polymarket `outcomePrices`."
        )
        event.final_notes.append(
            "`ТБ 1.5` и `ТБ 2.5` в этом отчёте приведены как decimal-implied odds из Polymarket, а не как классические букмекерские коэффициенты."
        )
    else:
        event.quality_notes.append(
            "`ТБ 1.5` / `ТБ 2.5`: Polymarket totals markets для текущих боёв автоматически не сматчились."
        )
    return event


def _extract_next_data(page_html: str) -> dict[str, Any]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json" crossorigin="anonymous">(.*?)</script>',
        page_html,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError("Could not find __NEXT_DATA__ on Polymarket UFC index page.")
    return json.loads(match.group(1))


def _extract_index_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    queries = payload.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
    for query in queries:
        data = query.get("state", {}).get("data", {})
        pages = data.get("pages") if isinstance(data, dict) else None
        if not isinstance(pages, list):
            continue
        for page in pages:
            for event in page.get("events", []):
                slug = event.get("slug")
                title = event.get("title")
                markets = event.get("markets")
                if slug and title and isinstance(markets, list) and slug not in seen:
                    seen.add(slug)
                    events.append(event)
    return events


def _match_event_for_bout(
    fighter_a_name: str,
    fighter_b_name: str,
    events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None
    for event in events:
        title = event.get("title", "")
        score = _title_match_score(title, fighter_a_name, fighter_b_name)
        if score < 8:
            continue
        if not best or score > best[0]:
            best = (score, event)
    return best[1] if best else None


def _title_match_score(title: str, fighter_a_name: str, fighter_b_name: str) -> int:
    title_score = fighter_name_score(title, fighter_a_name) + fighter_name_score(title, fighter_b_name)
    return title_score


def _extract_over_decimal(event: dict[str, Any], question: str) -> str:
    for market in event.get("markets", []):
        if market.get("question") != question:
            continue
        outcomes = market.get("outcomes", [])
        prices = market.get("outcomePrices", [])
        if not isinstance(outcomes, list) or not isinstance(prices, list):
            return "n/a"
        try:
            over_index = outcomes.index("Over")
        except ValueError:
            return "n/a"
        if over_index >= len(prices):
            return "n/a"
        return _probability_to_decimal(prices[over_index])
    return "n/a"


def _probability_to_decimal(raw_value: str) -> str:
    try:
        probability = float(raw_value)
    except (TypeError, ValueError):
        return "n/a"
    if probability <= 0:
        return "n/a"
    return f"{1 / probability:.2f}"
