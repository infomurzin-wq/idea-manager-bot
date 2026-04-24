from __future__ import annotations

import json
import re
from html import unescape
from typing import Any
from urllib.parse import quote_plus

from ..models import BoutSnapshot, EventSnapshot
from ..normalize import fighter_name_score, last_name, slugify
from .http import fetch_text

POSTS_API = "https://www.mmaoddsbreaker.com/wp-json/wp/v2/posts"


def enrich_event_with_opening_odds(event: EventSnapshot) -> EventSnapshot:
    article = find_opening_odds_article(event)
    if not article:
        event.quality_notes.append(
            "Moneyline: opening-odds article на MMAOddsBreaker для этого турнира автоматически не найдена, поэтому линии остались `n/a`."
        )
        return event

    odds_rows = parse_opening_odds_rows(article.get("content", {}).get("rendered", ""))
    if not odds_rows:
        event.quality_notes.append(
            "Moneyline: статья MMAOddsBreaker найдена, но odds-строки не распарсились из article body."
        )
        return event

    matched = 0
    used_rows: set[int] = set()
    for bout in event.bouts:
        match = match_bout_odds(bout, odds_rows, used_rows=used_rows)
        if not match:
            continue
        matched += 1
        used_rows.add(match["row_index"])
        if match["orientation"] == "direct":
            bout.fighter_a_moneyline_decimal = american_to_decimal(match["row"]["fighter_a_american"])
            bout.fighter_b_moneyline_decimal = american_to_decimal(match["row"]["fighter_b_american"])
        else:
            bout.fighter_a_moneyline_decimal = american_to_decimal(match["row"]["fighter_b_american"])
            bout.fighter_b_moneyline_decimal = american_to_decimal(match["row"]["fighter_a_american"])

    if matched:
        article_url = article.get("link", "n/a")
        source_link = f"[MMAOddsBreaker opening odds]({article_url})"
        if source_link not in event.primary_sources:
            event.primary_sources.append(source_link)
        if "mmaoddsbreaker_odds" not in event.source:
            event.source = f"{event.source} + mmaoddsbreaker_odds"
        event.quality_notes.append(
            f"Moneyline: {matched}/{len(event.bouts)} боёв обогащены opening odds из MMAOddsBreaker."
        )
        event.final_notes.append(
            "Moneyline в этом отчёте взят из opening odds статьи MMAOddsBreaker и приведён к decimal-формату."
        )
    else:
        event.quality_notes.append(
            "Moneyline: статья MMAOddsBreaker найдена, но строки не сматчились с текущей картой ESPN."
        )
    return event


def find_opening_odds_article(event: EventSnapshot) -> dict[str, Any] | None:
    search_terms = build_search_terms(event)
    seen_ids: set[int] = set()
    candidates: list[dict[str, Any]] = []
    for search_term in search_terms:
        url = f"{POSTS_API}?search={quote_plus(search_term)}&per_page=10"
        payload = json.loads(fetch_text(url, cache_namespace="mmaoddsbreaker_api"))
        if not isinstance(payload, list):
            continue
        for post in payload:
            post_id = int(post.get("id", 0) or 0)
            if not post_id or post_id in seen_ids:
                continue
            seen_ids.add(post_id)
            title = unescape(post.get("title", {}).get("rendered", ""))
            title_slug = slugify(title)
            if "opening-betting-odds" not in title_slug and "opening-odds" not in title_slug:
                continue
            if not event_title_match(event, title):
                continue
            candidates.append(post)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.get("date_gmt", ""), reverse=True)
    return candidates[0]


def build_search_terms(event: EventSnapshot) -> list[str]:
    terms: list[str] = []
    if event.bouts:
        main_bout = event.bouts[0]
        terms.append(f"{main_bout.fighter_a_name} {main_bout.fighter_b_name}")
        terms.append(f"{last_name(main_bout.fighter_a_name)} {last_name(main_bout.fighter_b_name)}")
    terms.append(event.event_name)
    terms.append(event.event_slug.replace("-", " "))
    return list(dict.fromkeys(term.strip() for term in terms if term.strip()))


def event_title_match(event: EventSnapshot, title: str) -> bool:
    normalized_title = slugify(title)
    if not event.bouts:
        return slugify(event.event_name) in normalized_title
    main_bout = event.bouts[0]
    return (
        slugify(last_name(main_bout.fighter_a_name)) in normalized_title
        and slugify(last_name(main_bout.fighter_b_name)) in normalized_title
    )


def parse_opening_odds_rows(content_html: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    paragraphs = re.findall(r"<p>(.*?)</p>", content_html, flags=re.IGNORECASE | re.DOTALL)
    for paragraph in paragraphs:
        if "<strong>" in paragraph.lower():
            continue
        cleaned = paragraph.replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        lines = [unescape(line).strip() for line in cleaned.splitlines() if line.strip()]
        if len(lines) != 2:
            continue
        fighter_a = _parse_odds_line(lines[0])
        fighter_b = _parse_odds_line(lines[1])
        if not fighter_a or not fighter_b:
            continue
        rows.append(
            {
                "fighter_a_name": fighter_a["name"],
                "fighter_a_american": fighter_a["american"],
                "fighter_b_name": fighter_b["name"],
                "fighter_b_american": fighter_b["american"],
            }
        )
    return rows


def _parse_odds_line(line: str) -> dict[str, str] | None:
    match = re.match(r"^(?P<name>.+?)\s+(?P<american>[+-]\d{3,4})$", line)
    if not match:
        return None
    return {
        "name": match.group("name").strip(),
        "american": match.group("american").strip(),
    }


def match_bout_odds(
    bout: BoutSnapshot,
    odds_rows: list[dict[str, str]],
    *,
    used_rows: set[int],
) -> dict[str, Any] | None:
    best_match: dict[str, Any] | None = None
    for index, row in enumerate(odds_rows):
        if index in used_rows:
            continue
        direct_score = _fighter_name_score(row["fighter_a_name"], bout.fighter_a_name) + _fighter_name_score(
            row["fighter_b_name"], bout.fighter_b_name
        )
        reverse_score = _fighter_name_score(row["fighter_a_name"], bout.fighter_b_name) + _fighter_name_score(
            row["fighter_b_name"], bout.fighter_a_name
        )
        score = max(direct_score, reverse_score)
        if score < 8:
            continue
        orientation = "direct" if direct_score >= reverse_score else "reverse"
        if not best_match or score > best_match["score"]:
            best_match = {
                "row_index": index,
                "row": row,
                "score": score,
                "orientation": orientation,
            }
    return best_match


def _fighter_name_score(source_name: str, target_name: str) -> int:
    return fighter_name_score(source_name, target_name)


def american_to_decimal(line: str) -> str:
    try:
        value = int(line)
    except ValueError:
        return "n/a"
    if value > 0:
        decimal = 1 + (value / 100)
    else:
        decimal = 1 + (100 / abs(value))
    return f"{decimal:.2f}"
