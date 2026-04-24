from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "-", ascii_value)
    return ascii_value.strip("-") or "ufc-event"


def strip_backticks(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("`") and cleaned.endswith("`"):
        return cleaned[1:-1]
    return cleaned


def name_tokens(value: str) -> list[str]:
    return [token for token in slugify(value).split("-") if token]


def last_name(value: str) -> str:
    tokens = name_tokens(value)
    return tokens[-1] if tokens else slugify(value)


def fighter_name_score(source_name: str, target_name: str) -> int:
    source_slug = slugify(source_name)
    target_slug = slugify(target_name)
    if source_slug == target_slug:
        return 10
    source = set(name_tokens(source_name))
    target = set(name_tokens(target_name))
    overlap = len(source & target)
    if last_name(source_name) == last_name(target_name):
        if overlap >= 2:
            return 8
        return 4
    if overlap >= 2:
        return 5
    if overlap == 1:
        return 1
    return 0


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def compute_content_hash(payload: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def report_payload_for_hash(payload: dict[str, Any]) -> dict[str, Any]:
    cloned = json.loads(json.dumps(payload, ensure_ascii=False))
    cloned.pop("generated_at", None)
    cloned.pop("content_hash", None)
    return cloned


def report_payload_for_meaningful_hash(payload: dict[str, Any]) -> dict[str, Any]:
    cloned = report_payload_for_hash(payload)
    return _normalize_meaningful_payload(cloned)


def dataclass_hash(payload: Any) -> str:
    return compute_content_hash(report_payload_for_hash(asdict(payload)))


def _normalize_meaningful_payload(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize_meaningful_payload(item, parent_key=key)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_normalize_meaningful_payload(item, parent_key=parent_key) for item in value]
    if parent_key in {"over_1_5_decimal", "over_2_5_decimal"} and isinstance(value, str):
        return _bucket_decimal_string(value, step=0.05)
    return value


def _bucket_decimal_string(raw_value: str, *, step: float) -> str:
    if raw_value == "n/a":
        return raw_value
    try:
        value = float(raw_value)
    except ValueError:
        return raw_value
    bucketed = round(value / step) * step
    return f"{bucketed:.2f}"
