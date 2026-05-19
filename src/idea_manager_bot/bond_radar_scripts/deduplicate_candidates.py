#!/usr/bin/env python3
"""Offline prototype: merge duplicate bond candidate cards from multiple sources."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any

import extract_candidate


EMPTY_VALUES = (None, "", "unknown", [])
STATUS_PRIORITY = {"interesting": 0, "needs_review": 1, "reject": 2}
COUPON_FIELDS = {"coupon", "coupon_raw", "coupon_min", "coupon_max"}
YTM_FIELDS = {"ytm", "ytm_raw", "ytm_min", "ytm_max"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and deduplicate bond candidate cards.")
    parser.add_argument("inputs", type=Path, nargs="+", help="JSONL post fixtures to process.")
    args = parser.parse_args()

    cards = extract_cards_from_files(args.inputs)
    for card in deduplicate_candidates(cards):
        print(json.dumps(card, ensure_ascii=False, sort_keys=True))


def extract_cards_from_files(paths: list[Path]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for path in paths:
        for post in extract_candidate.read_posts(path):
            cards.extend(extract_candidate.extract_candidates(post))
    return cards


def deduplicate_candidates(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_cards: list[dict[str, Any]] = []
    key_index: dict[str, int] = {}

    for card in cards:
        keys = candidate_keys(card)
        existing_index = next((key_index[key] for key in keys if key in key_index), None)

        if existing_index is None:
            merged = prepare_merged_card(card)
            merged_cards.append(merged)
            existing_index = len(merged_cards) - 1
        else:
            matched_key = next(key for key in keys if key in key_index)
            merge_into(merged_cards[existing_index], card, matched_key)

        for key in candidate_keys(merged_cards[existing_index]):
            key_index.setdefault(key, existing_index)

    return merged_cards


def prepare_merged_card(card: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(card)
    merged["dedup"] = {
        "primary_key": primary_key(merged),
        "source_count": 1,
        "sources": [copy.deepcopy(merged["source"])],
        "matched_keys": candidate_keys(merged),
        "conflicts": [],
    }
    return merged


def merge_into(base: dict[str, Any], incoming: dict[str, Any], matched_key: str) -> None:
    append_source(base, incoming["source"])
    base["dedup"]["matched_keys"] = sorted(set(base["dedup"]["matched_keys"]) | set(candidate_keys(incoming)) | {matched_key})

    for section in ("instrument", "terms"):
        for field, incoming_value in incoming[section].items():
            merge_field(base, incoming, section, field, incoming_value)

    base["assessment"]["red_flags"] = sorted(
        set(base["assessment"]["red_flags"]) | set(incoming["assessment"]["red_flags"])
    )
    base["assessment"]["missing_fields"] = sorted(
        extract_candidate.find_missing_fields(base["instrument"], base["terms"])
    )
    base["assessment"]["status"] = merge_status(
        base["assessment"]["status"],
        incoming["assessment"]["status"],
        base["assessment"]["missing_fields"],
        base["assessment"]["red_flags"],
    )
    if base["dedup"]["conflicts"]:
        base["assessment"]["interest_reason"] = (
            "Объединены несколько источников; нужны ручная сверка и разбор расхождений."
        )
    elif base["dedup"]["source_count"] > 1:
        base["assessment"]["interest_reason"] = "Объединены несколько источников по одной бумаге."
    base["dedup"]["primary_key"] = primary_key(base)


def merge_field(
    base: dict[str, Any],
    incoming: dict[str, Any],
    section: str,
    field: str,
    incoming_value: Any,
) -> None:
    current_value = base[section].get(field)
    if current_value == incoming_value:
        return

    if section == "terms" and field in COUPON_FIELDS and percent_terms_compatible(base["terms"], incoming["terms"], "coupon"):
        combine_percent_terms(base["terms"], incoming["terms"], "coupon")
        return
    if section == "terms" and field in YTM_FIELDS and percent_terms_compatible(base["terms"], incoming["terms"], "ytm"):
        combine_percent_terms(base["terms"], incoming["terms"], "ytm")
        return

    if current_value in EMPTY_VALUES and incoming_value not in EMPTY_VALUES:
        base[section][field] = copy.deepcopy(incoming_value)
        return
    if current_value not in EMPTY_VALUES and incoming_value not in EMPTY_VALUES and current_value != incoming_value:
        add_conflict(base, f"{section}.{field}", current_value, incoming_value, incoming["source"])


def percent_terms_compatible(base_terms: dict[str, Any], incoming_terms: dict[str, Any], field_prefix: str) -> bool:
    base_range = percent_range(base_terms, field_prefix)
    incoming_range = percent_range(incoming_terms, field_prefix)
    if not base_range or not incoming_range:
        return False
    return ranges_overlap(base_range, incoming_range)


def combine_percent_terms(base_terms: dict[str, Any], incoming_terms: dict[str, Any], field_prefix: str) -> None:
    base_range = percent_range(base_terms, field_prefix)
    incoming_range = percent_range(incoming_terms, field_prefix)
    if not base_range and not incoming_range:
        return
    ranges = [item for item in (base_range, incoming_range) if item]
    low = min(item[0] for item in ranges)
    high = max(item[1] for item in ranges)
    base_terms[field_prefix] = format_percent_number(high)
    base_terms[f"{field_prefix}_min"] = format_percent_number(low)
    base_terms[f"{field_prefix}_max"] = format_percent_number(high)
    base_terms[f"{field_prefix}_raw"] = (
        format_percent_number(high)
        if low == high
        else f"{format_percent_number(low).removesuffix('%')}-{format_percent_number(high)}"
    )


def percent_range(terms: dict[str, Any], field_prefix: str) -> tuple[float, float] | None:
    low = percent_to_float(terms.get(f"{field_prefix}_min"))
    high = percent_to_float(terms.get(f"{field_prefix}_max"))
    if low is not None and high is not None:
        return min(low, high), max(low, high)

    value = percent_to_float(terms.get(field_prefix))
    if value is not None:
        return value, value
    return None


def ranges_overlap(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return max(left[0], right[0]) <= min(left[1], right[1])


def percent_to_float(value: Any) -> float | None:
    if value in EMPTY_VALUES:
        return None
    text = str(value).strip().replace(",", ".").removesuffix("%")
    try:
        return float(text)
    except ValueError:
        return None


def format_percent_number(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def append_source(base: dict[str, Any], source: dict[str, Any]) -> None:
    source_copy = copy.deepcopy(source)
    if source_copy not in base["dedup"]["sources"]:
        base["dedup"]["sources"].append(source_copy)
    base["dedup"]["source_count"] = len(base["dedup"]["sources"])


def add_conflict(
    base: dict[str, Any],
    field: str,
    kept: Any,
    incoming: Any,
    source: dict[str, Any],
) -> None:
    conflict = {
        "field": field,
        "kept": kept,
        "incoming": incoming,
        "source": copy.deepcopy(source),
    }
    if conflict not in base["dedup"]["conflicts"]:
        base["dedup"]["conflicts"].append(conflict)


def merge_status(current: str, incoming: str, missing_fields: list[str], red_flags: list[str]) -> str:
    if STATUS_PRIORITY[incoming] > STATUS_PRIORITY[current]:
        current = incoming
    if "floating_coupon" in red_flags or "qualified_investors_only" in red_flags:
        return "reject"
    if red_flags and current == "interesting":
        return "needs_review"
    return current


def candidate_keys(card: dict[str, Any]) -> list[str]:
    instrument = card["instrument"]
    terms = card["terms"]
    issuer = normalize_free_text(instrument.get("issuer"))
    issue = normalize_issue(instrument.get("issue_name"))
    isin = normalize_isin(instrument.get("isin"))
    book_date = normalize_date_value(terms.get("book_building_date"))
    placement_date = normalize_date_value(terms.get("placement_date"))
    source = card["source"]

    keys: list[str] = []
    if isin:
        keys.append(f"isin:{isin}")
    if issuer and issue:
        keys.append(f"issuer_issue:{issuer}|{issue}")
        if book_date:
            keys.append(f"issuer_issue_book:{issuer}|{issue}|{book_date}")
    if issuer and card.get("signal_type") == "new_placement":
        if book_date:
            keys.append(f"issuer_book:{issuer}|{book_date}")
        if placement_date:
            keys.append(f"issuer_placement:{issuer}|{placement_date}")
    if not keys:
        keys.append(
            "source:"
            f"{source.get('channel') or ''}|{source.get('post_id') or ''}|"
            f"{source.get('url') or ''}|{source.get('block_index') or ''}"
        )
    return unique(keys)


def primary_key(card: dict[str, Any]) -> str:
    return candidate_keys(card)[0]


def normalize_isin(value: Any) -> str | None:
    if value in EMPTY_VALUES:
        return None
    return extract_candidate.normalize_for_codes(str(value)).upper()


def normalize_issue(value: Any) -> str | None:
    if value in EMPTY_VALUES:
        return None
    normalized = extract_candidate.normalize_for_codes(str(value)).upper()
    return re.sub(r"[^0-9A-ZА-Я]+", "", normalized) or None


def normalize_date_value(value: Any) -> str | None:
    if value in EMPTY_VALUES:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
        return text
    return None


def normalize_free_text(value: Any) -> str | None:
    if value in EMPTY_VALUES:
        return None
    text = str(value).lower().replace("ё", "е")
    text = re.sub(r"\b(?:ооо|ао|пао)\b", "", text)
    text = re.sub(r"[^0-9a-zа-я]+", "", text)
    return text or None


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


if __name__ == "__main__":
    main()
