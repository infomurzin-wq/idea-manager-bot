#!/usr/bin/env python3
"""Offline JSONL storage for deduplicated bond candidates."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import deduplicate_candidates


VALID_STATUSES = {"new", "watchlist", "rejected"}
DEFAULT_STORE_PATH = Path("04_projects/bond-radar-bot/data/candidates_store.jsonl")
EDITABLE_FIELD_PATHS = {
    "issuer": ("instrument", "issuer"),
    "issue_name": ("instrument", "issue_name"),
    "isin": ("instrument", "isin"),
    "rating": ("instrument", "rating"),
    "coupon": ("terms", "coupon"),
    "ytm": ("terms", "ytm"),
    "coupon_frequency_per_year": ("terms", "coupon_frequency_per_year"),
    "coupon_type": ("terms", "coupon_type"),
    "price": ("terms", "price"),
    "book_building_date": ("terms", "book_building_date"),
    "placement_date": ("terms", "placement_date"),
    "first_trading_date": ("terms", "first_trading_date"),
    "maturity_date": ("terms", "maturity_date"),
    "offer": ("terms", "offer"),
    "amortization": ("terms", "amortization"),
    "issue_size": ("terms", "issue_size"),
    "qualified_only": ("terms", "qualified_only"),
}
CRITICAL_FIELDS = {
    "issuer",
    "coupon",
    "ytm",
    "book_building_date",
    "placement_date",
    "maturity_date",
    "offer",
    "amortization",
    "coupon_frequency_per_year",
    "coupon_type",
    "rating",
}
EDITABLE_RED_FLAGS = {
    "floating_coupon",
    "offer_present_or_needs_review",
    "amortization_present_or_needs_review",
    "qualified_investors_only",
}


@dataclass
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


def main() -> None:
    raw_args = sys.argv[1:]
    if raw_args and raw_args[0] not in {"import", "set-status", "delete", "list", "show"}:
        raw_args = ["import", *raw_args]

    parser = argparse.ArgumentParser(description="Persist and update deduplicated bond candidates.")
    subparsers = parser.add_subparsers(dest="command")

    import_parser = subparsers.add_parser("import", help="Import post fixtures into the candidate store.")
    import_parser.add_argument("inputs", type=Path, nargs="+", help="JSONL post fixtures to process.")
    import_parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH, help="JSONL candidate store path.")
    import_parser.add_argument("--status", choices=sorted(VALID_STATUSES), default="new", help="Status for newly inserted candidates.")

    status_parser = subparsers.add_parser("set-status", help="Set lifecycle status for an existing candidate.")
    status_parser.add_argument("key", help="storage.key, dedup key, ISIN key, or another matched candidate key.")
    status_parser.add_argument("status", choices=sorted(VALID_STATUSES), help="New lifecycle status.")
    status_parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH, help="JSONL candidate store path.")

    delete_parser = subparsers.add_parser("delete", help="Delete an existing candidate from the store.")
    delete_parser.add_argument("key", help="storage.key, dedup key, ISIN key, or another matched candidate key.")
    delete_parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH, help="JSONL candidate store path.")

    list_parser = subparsers.add_parser("list", help="List candidates from the store.")
    list_parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH, help="JSONL candidate store path.")
    list_parser.add_argument("--status", choices=sorted(VALID_STATUSES), help="Optional lifecycle status filter.")
    list_parser.add_argument(
        "--format",
        choices=("compact-jsonl", "jsonl"),
        default="compact-jsonl",
        help="Output compact list rows or full JSONL records.",
    )

    show_parser = subparsers.add_parser("show", help="Show one full candidate record.")
    show_parser.add_argument("key", help="storage.key, dedup key, ISIN key, or another matched candidate key.")
    show_parser.add_argument("--store", type=Path, default=DEFAULT_STORE_PATH, help="JSONL candidate store path.")

    args = parser.parse_args(raw_args)

    if args.command is None:
        parser.error("use `import` or `set-status`")

    if args.command == "set-status":
        records = load_store(args.store)
        record = set_candidate_status(records, args.key, args.status)
        write_store(args.store, records)
        print(
            json.dumps(
                {
                    "key": record["storage"]["key"],
                    "status": record["storage"]["status"],
                    "store": str(args.store),
                    "updated_at": record["storage"]["updated_at"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return

    if args.command == "delete":
        records = load_store(args.store)
        record = delete_candidate(records, args.key)
        write_store(args.store, records)
        print(
            json.dumps(
                {
                    "deleted_key": record["storage"]["key"],
                    "store_records": len(records),
                    "store": str(args.store),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return

    if args.command == "list":
        records = load_store(args.store)
        for record in list_candidates(records, status=args.status):
            item = record if args.format == "jsonl" else compact_list_item(record)
            print(json.dumps(item, ensure_ascii=False, sort_keys=True))
        return

    if args.command == "show":
        records = load_store(args.store)
        record = get_candidate(records, args.key)
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return

    cards = deduplicate_candidates.extract_cards_from_files(args.inputs)
    merged_cards = deduplicate_candidates.deduplicate_candidates(cards)
    records = load_store(args.store)
    result = upsert_candidates(records, merged_cards, new_status=args.status)
    write_store(args.store, records)

    print(
        json.dumps(
            {
                "input_cards": len(cards),
                "merged_candidates": len(merged_cards),
                "store_records": len(records),
                "inserted": result.inserted,
                "updated": result.updated,
                "unchanged": result.unchanged,
                "store": str(args.store),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def load_store(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}

    records: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            key = record.get("storage", {}).get("key")
            if not key:
                raise ValueError(f"Missing storage.key at {path}:{line_number}")
            records[key] = record
    return records


def write_store(path: Path, records: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        for key in sorted(records):
            file.write(json.dumps(records[key], ensure_ascii=False, sort_keys=True))
            file.write("\n")
    temp_path.replace(path)


def upsert_candidates(
    records: dict[str, dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    new_status: str = "new",
    now: datetime | None = None,
) -> UpsertResult:
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Unsupported status: {new_status}")

    timestamp = iso_timestamp(now)
    result = UpsertResult()

    for candidate in candidates:
        matched_key = find_existing_key(records, candidate)
        if matched_key is None:
            key = stable_key(candidate)
            records[key] = make_record(candidate, key, new_status, timestamp)
            result.inserted += 1
            continue

        changed = merge_record(records[matched_key], candidate, timestamp)
        if changed:
            result.updated += 1
        else:
            result.unchanged += 1

    return result


def set_candidate_status(
    records: dict[str, dict[str, Any]],
    lookup_key: str,
    status: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Unsupported status: {status}")

    matched_key = find_existing_record_key(records, lookup_key)
    if matched_key is None:
        raise KeyError(f"Candidate not found: {lookup_key}")

    record = records[matched_key]
    timestamp = iso_timestamp(now)
    if record["storage"]["status"] != status:
        record["storage"]["status"] = status
        record["storage"]["updated_at"] = timestamp
    return record


def get_candidate(records: dict[str, dict[str, Any]], lookup_key: str) -> dict[str, Any]:
    matched_key = find_existing_record_key(records, lookup_key)
    if matched_key is None:
        raise KeyError(f"Candidate not found: {lookup_key}")
    return records[matched_key]


def delete_candidate(records: dict[str, dict[str, Any]], lookup_key: str) -> dict[str, Any]:
    matched_key = find_existing_record_key(records, lookup_key)
    if matched_key is None:
        raise KeyError(f"Candidate not found: {lookup_key}")
    return records.pop(matched_key)


def merge_candidate_into_record(
    records: dict[str, dict[str, Any]],
    lookup_key: str,
    candidate: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    matched_key = find_existing_record_key(records, lookup_key)
    if matched_key is None:
        raise KeyError(f"Candidate not found: {lookup_key}")

    record = records[matched_key]
    merge_record(record, candidate, iso_timestamp(now))
    return record


def update_candidate_field(
    records: dict[str, dict[str, Any]],
    lookup_key: str,
    field: str,
    raw_value: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if field not in EDITABLE_FIELD_PATHS:
        raise ValueError(f"Unsupported editable field: {field}")

    matched_key = find_existing_record_key(records, lookup_key)
    if matched_key is None:
        raise KeyError(f"Candidate not found: {lookup_key}")

    record = records[matched_key]
    candidate = record["candidate"]
    section, key = EDITABLE_FIELD_PATHS[field]
    value = normalize_manual_field_value(field, raw_value)
    candidate[section][key] = value
    if field == "coupon":
        candidate["terms"]["coupon_raw"] = value
    elif field == "ytm":
        candidate["terms"]["ytm_raw"] = value

    refresh_manual_assessment(candidate)
    normalize_candidate_for_store(candidate)
    record["storage"]["updated_at"] = iso_timestamp(now)
    return record


def list_candidates(
    records: dict[str, dict[str, Any]],
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"Unsupported status: {status}")

    items = [record for record in records.values() if status is None or record["storage"]["status"] == status]
    return sorted(items, key=list_sort_key)


def compact_list_item(record: dict[str, Any]) -> dict[str, Any]:
    candidate = record["candidate"]
    instrument = candidate["instrument"]
    terms = candidate["terms"]
    assessment = candidate["assessment"]
    return {
        "key": record["storage"]["key"],
        "status": record["storage"]["status"],
        "issuer": instrument.get("issuer"),
        "issue_name": instrument.get("issue_name"),
        "isin": instrument.get("isin"),
        "rating": instrument.get("rating"),
        "coupon": terms.get("coupon_raw") or terms.get("coupon"),
        "ytm": terms.get("ytm_raw") or terms.get("ytm"),
        "book_building_date": terms.get("book_building_date"),
        "placement_date": terms.get("placement_date"),
        "maturity_date": terms.get("maturity_date"),
        "assessment_status": assessment.get("status"),
        "red_flags": assessment.get("red_flags", []),
        "source_count": candidate.get("dedup", {}).get("source_count"),
        "updated_at": record["storage"]["updated_at"],
    }


def list_sort_key(record: dict[str, Any]) -> tuple[str, str, str]:
    candidate = record["candidate"]
    terms = candidate["terms"]
    instrument = candidate["instrument"]
    return (
        terms.get("book_building_date") or "99.99.9999",
        instrument.get("issuer") or "",
        instrument.get("issue_name") or "",
    )


def make_record(candidate: dict[str, Any], key: str, status: str, timestamp: str) -> dict[str, Any]:
    stored_candidate = copy.deepcopy(candidate)
    stored_candidate["dedup"]["primary_key"] = key
    normalize_candidate_for_store(stored_candidate)
    return {
        "storage": {
            "key": key,
            "status": status,
            "created_at": timestamp,
            "updated_at": timestamp,
            "seen_count": stored_candidate["dedup"]["source_count"],
        },
        "candidate": stored_candidate,
    }


def merge_record(record: dict[str, Any], incoming: dict[str, Any], timestamp: str) -> bool:
    before = json.dumps(record["candidate"], ensure_ascii=False, sort_keys=True)
    storage_key = record["storage"]["key"]
    incoming_copy = copy.deepcopy(incoming)

    for source in incoming_copy.get("dedup", {}).get("sources", []):
        deduplicate_candidates.append_source(record["candidate"], source)
    record["candidate"]["dedup"]["matched_keys"] = sorted(
        set(record["candidate"]["dedup"].get("matched_keys", []))
        | set(incoming_copy.get("dedup", {}).get("matched_keys", []))
        | set(deduplicate_candidates.candidate_keys(incoming_copy))
        | {storage_key}
    )
    deduplicate_candidates.merge_into(record["candidate"], incoming_copy, storage_key)
    record["candidate"]["dedup"]["primary_key"] = storage_key
    normalize_candidate_for_store(record["candidate"])

    after = json.dumps(record["candidate"], ensure_ascii=False, sort_keys=True)
    if before == after:
        return False

    record["storage"]["updated_at"] = timestamp
    record["storage"]["seen_count"] = record["candidate"]["dedup"]["source_count"]
    return True


def normalize_candidate_for_store(candidate: dict[str, Any]) -> None:
    candidate["assessment"]["red_flags"] = sorted(candidate["assessment"].get("red_flags", []))
    candidate["assessment"]["missing_fields"] = sorted(candidate["assessment"].get("missing_fields", []))
    candidate["dedup"]["matched_keys"] = sorted(set(candidate["dedup"].get("matched_keys", [])))


def normalize_manual_field_value(field: str, raw_value: str) -> Any:
    value = raw_value.strip()
    lowered = value.lower()
    if lowered in {"", "-", "пусто", "очистить", "clear", "null"}:
        return None
    if field == "isin":
        return reformat_isin(value)
    if field == "coupon_frequency_per_year":
        match = next(iter(re.findall(r"\d+", value)), None)
        return int(match) if match else value
    if field == "coupon_type":
        if lowered in {"фикс", "фиксированный", "fixed"}:
            return "fixed"
        if lowered in {"флоатер", "плавающий", "floating"}:
            return "floating"
        return "unknown" if lowered in {"unknown", "неизвестно", "нужно проверить"} else value
    if field in {"offer", "amortization"} and lowered in {"нет", "no", "без", "отсутствует"}:
        return "no"
    if field == "qualified_only":
        if lowered in {"да", "yes", "true", "1", "квал", "только квалы"}:
            return True
        if lowered in {"нет", "no", "false", "0", "неквал", "для всех"}:
            return False
    return value


def reformat_isin(value: str) -> str:
    return "".join(value.split()).upper()


def refresh_manual_assessment(candidate: dict[str, Any]) -> None:
    instrument = candidate["instrument"]
    terms = candidate["terms"]
    missing = set(candidate["assessment"].get("missing_fields", []))
    for field in CRITICAL_FIELDS:
        source = instrument if field in instrument else terms
        if source.get(field) in (None, "", "unknown"):
            missing.add(field)
        else:
            missing.discard(field)
    candidate["assessment"]["missing_fields"] = sorted(missing)

    red_flags = set(candidate["assessment"].get("red_flags", [])) - EDITABLE_RED_FLAGS
    if terms.get("coupon_type") == "floating":
        red_flags.add("floating_coupon")
    if terms.get("offer") and terms.get("offer") != "no":
        red_flags.add("offer_present_or_needs_review")
    if terms.get("amortization") and terms.get("amortization") != "no":
        red_flags.add("amortization_present_or_needs_review")
    if terms.get("qualified_only") is True:
        red_flags.add("qualified_investors_only")
    candidate["assessment"]["red_flags"] = sorted(red_flags)


def find_existing_key(records: dict[str, dict[str, Any]], candidate: dict[str, Any]) -> str | None:
    index: dict[str, str] = {}
    for key, record in records.items():
        index[key] = key
        for candidate_key in all_candidate_keys(record["candidate"]):
            index[candidate_key] = key

    for candidate_key in all_candidate_keys(candidate):
        if candidate_key in index:
            return index[candidate_key]
    return None


def find_existing_record_key(records: dict[str, dict[str, Any]], lookup_key: str) -> str | None:
    if lookup_key in records:
        return lookup_key

    normalized_lookup = normalize_lookup_key(lookup_key)
    for key, record in records.items():
        if normalize_lookup_key(key) == normalized_lookup:
            return key
        for candidate_key in all_candidate_keys(record["candidate"]):
            if normalize_lookup_key(candidate_key) == normalized_lookup:
                return key
    return None


def normalize_lookup_key(value: str) -> str:
    return value.strip().lower()


def all_candidate_keys(candidate: dict[str, Any]) -> list[str]:
    keys = [stable_key(candidate)]
    keys.extend(candidate.get("dedup", {}).get("matched_keys", []))
    keys.extend(deduplicate_candidates.candidate_keys(candidate))
    return unique(keys)


def stable_key(candidate: dict[str, Any]) -> str:
    return candidate.get("dedup", {}).get("primary_key") or deduplicate_candidates.primary_key(candidate)


def iso_timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds")


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
