from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from lxml import html as lxml_html

from .http import fetch_text

ESPN_UFC_SCHEDULE_URL = "https://www.espn.com/mma/schedule/_/league/ufc"
ESPN_UFC_CORE_EVENTS_URL = "https://sports.core.api.espn.com/v2/sports/mma/leagues/ufc/events"


@dataclass(frozen=True)
class ScheduledEvent:
    event_date: str
    event_name: str
    event_url: str
    event_time: str
    broadcast: str
    location: str


def list_scheduled_events(reference_date: date) -> list[ScheduledEvent]:
    events: list[ScheduledEvent] = []
    seen_urls: set[str] = set()

    for event in _list_core_api_events(reference_date):
        if not is_supported_ufc_event_name(event.event_name):
            continue
        if event.event_url in seen_urls:
            continue
        seen_urls.add(event.event_url)
        events.append(event)

    for schedule_url in _schedule_urls(reference_date):
        try:
            page_html = fetch_text(schedule_url, cache_namespace="espn_schedule")
        except Exception:
            continue
        if not page_html.strip():
            continue
        try:
            document = lxml_html.fromstring(page_html)
        except Exception:
            continue

        rows = document.xpath("//a[contains(@href, '/mma/fightcenter/_/id/')]/ancestor::tr[1]")
        for row in rows:
            anchor = row.xpath(".//a[contains(@href, '/mma/fightcenter/_/id/')][1]")
            cells = row.xpath("./td")
            if not anchor or len(cells) < 5:
                continue
            event_url = urljoin("https://www.espn.com", anchor[0].get("href", "").strip())
            if not event_url or event_url in seen_urls:
                continue
            event_name = _text_content(cells[3])
            if not is_supported_ufc_event_name(event_name):
                continue
            seen_urls.add(event_url)
            raw_date = _text_content(cells[0])
            parsed_date = _infer_event_date(raw_date, reference_date)
            if parsed_date is None:
                continue
            events.append(
                ScheduledEvent(
                    event_date=parsed_date.isoformat(),
                    event_name=event_name,
                    event_url=event_url,
                    event_time=_text_content(cells[1]),
                    broadcast=_text_content(cells[2]),
                    location=_text_content(cells[4]),
                )
            )
    events.sort(key=lambda event: event.event_date)
    return events


def find_nearest_weekend_event(reference_date: date) -> ScheduledEvent | None:
    weekend_dates = set(next_weekend_dates(reference_date))
    for event in list_scheduled_events(reference_date):
        event_day = date.fromisoformat(event.event_date)
        if event_day in weekend_dates:
            return event
    return None


def next_weekend_dates(reference_date: date) -> tuple[date, date]:
    saturday_offset = (5 - reference_date.weekday()) % 7
    saturday = reference_date + timedelta(days=saturday_offset)
    sunday = saturday + timedelta(days=1)
    return saturday, sunday


def is_supported_ufc_event_name(event_name: str) -> bool:
    normalized = " ".join(event_name.split()).lower()
    if normalized.startswith("road to ufc"):
        return False
    if normalized.startswith("ufc fight night"):
        return True
    return re.match(r"^ufc\s+\d+\b", normalized) is not None


def _schedule_urls(reference_date: date) -> list[str]:
    year = reference_date.year
    return [
        f"https://www.espn.com/mma/schedule/_/year/{year}/league/ufc",
        f"https://www.espn.com/mma/schedule/_/league/ufc/year/{year}",
        ESPN_UFC_SCHEDULE_URL,
    ]


def _list_core_api_events(reference_date: date) -> list[ScheduledEvent]:
    year = reference_date.year
    page = 1
    events: list[ScheduledEvent] = []
    page_count = 1

    while page <= page_count:
        index_url = f"{ESPN_UFC_CORE_EVENTS_URL}?dates={year}&page={page}"
        try:
            payload = json.loads(fetch_text(index_url, cache_namespace="espn_core_events"))
        except Exception:
            break

        if page == 1:
            page_count = int(payload.get("pageCount", 1) or 1)

        for item in payload.get("items", []):
            ref = item.get("$ref")
            if not isinstance(ref, str) or not ref:
                continue
            try:
                event_payload = json.loads(fetch_text(_https_url(ref), cache_namespace="espn_core_events"))
            except Exception:
                continue
            event = _core_event_from_payload(event_payload)
            if event is not None:
                events.append(event)
        page += 1

    return events


def _core_event_from_payload(payload: dict[str, object]) -> ScheduledEvent | None:
    event_id = str(payload.get("id") or "").strip()
    event_name = str(payload.get("name") or "").strip()
    event_date = _date_from_iso(str(payload.get("date") or ""))
    if not event_id or not event_name or event_date is None:
        return None

    event_url = _core_event_url(payload, event_id)
    return ScheduledEvent(
        event_date=event_date.isoformat(),
        event_name=event_name,
        event_url=event_url,
        event_time=_time_from_iso(str(payload.get("date") or "")),
        broadcast="n/a",
        location=_core_event_location(payload),
    )


def _core_event_url(payload: dict[str, object], event_id: str) -> str:
    links = payload.get("links")
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            href = str(link.get("href") or "").strip()
            rel = link.get("rel")
            if href.startswith("https://www.espn.com/mma/fightcenter/") and (
                not isinstance(rel, list) or "event" in rel
            ):
                return href
    return f"https://www.espn.com/mma/fightcenter/_/id/{event_id}/league/ufc"


def _core_event_location(payload: dict[str, object]) -> str:
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


def _date_from_iso(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _time_from_iso(value: str) -> str:
    if not value:
        return "n/a"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "n/a"
    return parsed.strftime("%H:%M UTC")


def _https_url(value: str) -> str:
    if value.startswith("http://"):
        return f"https://{value.removeprefix('http://')}"
    return value


def _text_content(node: object) -> str:
    if hasattr(node, "text_content"):
        return " ".join(part.strip() for part in node.text_content().splitlines() if part.strip())
    return "n/a"


def _infer_event_date(raw_value: str, reference_date: date) -> date | None:
    pieces = raw_value.replace(",", "").split()
    if len(pieces) < 2:
        return None
    month_name, day_value = pieces[0], pieces[1]
    try:
        month = _month_number(month_name)
        day = int(day_value)
    except ValueError:
        return None
    candidate = date(reference_date.year, month, day)
    if candidate < reference_date - timedelta(days=180):
        candidate = date(reference_date.year + 1, month, day)
    return candidate


def _month_number(value: str) -> int:
    mapping = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }
    if value not in mapping:
        raise ValueError(f"Unknown month abbreviation: {value}")
    return mapping[value]
