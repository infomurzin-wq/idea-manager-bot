"""Read UFC outcome quotes from Polymarket without placing orders."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen

from .models import EventSnapshot
from .sources.polymarket import _fetch_gamma_events, _match_event_for_bout, _parse_polymarket_list

BOOKS_URL = "https://clob.polymarket.com/books"
MARKET_URL = "https://gamma-api.polymarket.com/markets/{}"
MIN_DECIMAL = Decimal("1.70")


def _json_request(url: str, payload: object | None = None) -> object:
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "ufc-report-paper/1.0"},
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def _decimal(value: object) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None
    return result if result.is_finite() else None


def _books(token_ids: list[str]) -> dict[str, dict]:
    books: dict[str, dict] = {}
    for start in range(0, len(token_ids), 500):
        response = _json_request(
            BOOKS_URL, [{"token_id": token} for token in token_ids[start : start + 500]]
        )
        if not isinstance(response, list):
            raise ValueError("Polymarket returned an invalid order-book batch")
        books.update(
            (str(book["asset_id"]), book)
            for book in response
            if isinstance(book, dict) and book.get("asset_id")
        )
    return books


def discover_singles(event: EventSnapshot) -> list[dict]:
    """Return all active matched outcomes with best-ask implied decimal >= 1.70."""
    number = re.search(r"\bUFC\s+\d+\b", event.event_name, re.IGNORECASE)
    events = _fetch_gamma_events(number.group() if number else "UFC Fight Night")
    raw: list[dict] = []
    seen_tokens: set[str] = set()
    for bout in event.bouts:
        matched = _match_event_for_bout(bout.fighter_a_name, bout.fighter_b_name, events)
        if not matched:
            continue
        for market in matched.get("markets", []):
            if market.get("closed") or market.get("active") is not True or market.get("acceptingOrders") is not True:
                continue
            outcomes = _parse_polymarket_list(market.get("outcomes", []))
            tokens = _parse_polymarket_list(market.get("clobTokenIds", []))
            if not isinstance(outcomes, list) or not isinstance(tokens, list):
                continue
            for index, outcome in enumerate(outcomes):
                if index >= len(tokens) or not tokens[index]:
                    continue
                token = str(tokens[index])
                if token in seen_tokens:
                    continue
                seen_tokens.add(token)
                raw.append(
                    {
                        "event_slug": event.event_slug,
                        "event_name": event.event_name,
                        "event_date": event.event_date,
                        "bout_id": bout.bout_id,
                        "bout": f"{bout.fighter_a_name} — {bout.fighter_b_name}",
                        "question": str(market.get("question") or ""),
                        "outcome": str(outcome),
                        "market_id": str(market["id"]),
                        "token_id": token,
                    }
                )
    books = _books([item["token_id"] for item in raw]) if raw else {}
    captured_at = datetime.now(UTC).isoformat()
    found: list[dict] = []
    for item in raw:
        book = books.get(item["token_id"], {})
        prices = [_decimal(level.get("price")) for level in book.get("asks", [])]
        asks = [price for price in prices if price is not None and 0 < price < 1]
        if not asks:
            continue
        ask = min(asks)
        odds = Decimal(1) / ask
        if odds < MIN_DECIMAL:
            continue
        item.update(
            ask=str(ask),
            decimal=str(odds.quantize(Decimal("0.0001"))),
            captured_at=captured_at,
        )
        found.append(item)
    return sorted(found, key=lambda item: (item["bout"], item["question"], item["outcome"]))


def resolved_payout_factor(market_id: str, token_id: str) -> Decimal | None:
    market = _json_request(MARKET_URL.format(market_id))
    if not isinstance(market, dict) or not market.get("closed") or market.get("acceptingOrders") is True:
        return None
    tokens = _parse_polymarket_list(market.get("clobTokenIds", []))
    prices = _parse_polymarket_list(market.get("outcomePrices", []))
    if not isinstance(tokens, list) or not isinstance(prices, list):
        return None
    try:
        index = [str(token) for token in tokens].index(str(token_id))
    except ValueError:
        return None
    if index >= len(prices):
        return None
    factor = _decimal(prices[index])
    return factor if factor in {Decimal(0), Decimal("0.5"), Decimal(1)} else None
