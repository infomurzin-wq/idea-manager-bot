from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urljoin

from lxml import html as lxml_html

from .http import fetch_text

ESPN_UFC_SCHEDULE_URL = "https://www.espn.com/mma/schedule/_/league/ufc"


@dataclass(frozen=True)
class ScheduledEvent:
    event_date: str
    event_name: str
    event_url: str
    event_time: str
    broadcast: str
    location: str


def list_scheduled_events(reference_date: date) -> list[ScheduledEvent]:
    page_html = fetch_text(ESPN_UFC_SCHEDULE_URL, cache_namespace="espn_schedule")
    document = lxml_html.fromstring(page_html)
    rows = document.xpath("//a[contains(@href, '/mma/fightcenter/_/id/')]/ancestor::tr[1]")
    events: list[ScheduledEvent] = []
    seen_urls: set[str] = set()
    for row in rows:
        anchor = row.xpath(".//a[contains(@href, '/mma/fightcenter/_/id/')][1]")
        cells = row.xpath("./td")
        if not anchor or len(cells) < 5:
            continue
        event_url = urljoin("https://www.espn.com", anchor[0].get("href", "").strip())
        if not event_url or event_url in seen_urls:
            continue
        seen_urls.add(event_url)
        raw_date = _text_content(cells[0])
        parsed_date = _infer_event_date(raw_date, reference_date)
        if parsed_date is None:
            continue
        events.append(
            ScheduledEvent(
                event_date=parsed_date.isoformat(),
                event_name=_text_content(cells[3]),
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
