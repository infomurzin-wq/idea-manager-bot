from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import get_paths
from .models import ReportSnapshot
from .normalize import canonical_json


def ensure_runtime_dirs() -> None:
    paths = get_paths()
    for directory in (
        paths.runtime_root,
        paths.runtime_cache_dir,
        paths.runtime_reports_dir,
        paths.runtime_state_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def snapshot_dir_for_event(event_slug: str) -> Path:
    ensure_runtime_dirs()
    directory = get_paths().runtime_reports_dir / event_slug
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_snapshot(report: ReportSnapshot) -> Path:
    target = snapshot_dir_for_event(report.event.event_slug) / "report_snapshot.json"
    target.write_text(canonical_json(report.to_dict()) + "\n", encoding="utf-8")
    return target


def load_snapshot(path_or_slug: str) -> ReportSnapshot:
    resolved = resolve_snapshot_path(path_or_slug)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    return ReportSnapshot.from_dict(payload)


def resolve_snapshot_path(path_or_slug: str) -> Path:
    candidate = Path(path_or_slug)
    if candidate.exists():
        return candidate
    inferred = get_paths().runtime_reports_dir / path_or_slug / "report_snapshot.json"
    if inferred.exists():
        return inferred
    raise FileNotFoundError(
        f"Snapshot not found: {path_or_slug}. Checked direct path and runtime slug path."
    )


def write_rendered_markdown(event_slug: str, markdown: str, filename: str) -> Path:
    target = snapshot_dir_for_event(event_slug) / filename
    target.write_text(markdown, encoding="utf-8")
    return target


def load_active_weekend_event() -> dict[str, Any] | None:
    return _load_state_json("active_weekend_event.json")


def write_active_weekend_event(
    *,
    event_slug: str,
    event_date: str,
    event_url: str,
    window_opened_at: str,
    window_status: str,
) -> Path:
    payload = {
        "event_slug": event_slug,
        "event_date": event_date,
        "event_url": event_url,
        "window_opened_at": window_opened_at,
        "window_status": window_status,
    }
    return _write_state_json("active_weekend_event.json", payload)


def clear_active_weekend_event() -> None:
    target = get_paths().runtime_state_dir / "active_weekend_event.json"
    if target.exists():
        target.unlink()


def load_sent_reports_state() -> dict[str, Any]:
    payload = _load_state_json("sent_reports.json")
    if isinstance(payload, dict):
        return payload
    return {}


def load_last_sent_report(event_slug: str) -> dict[str, Any] | None:
    return load_sent_reports_state().get(event_slug)


def update_sent_report_state(
    *,
    event_slug: str,
    report: ReportSnapshot,
    meaningful_hash: str,
    report_kind: str,
    markdown_path: Path,
    send_target: str,
) -> Path:
    payload = load_sent_reports_state()
    payload[event_slug] = {
        "event_slug": event_slug,
        "last_sent_hash": report.content_hash,
        "last_sent_at": report.generated_at,
        "last_sent_kind": report_kind,
        "last_sent_path": str(markdown_path),
        "last_send_target": send_target,
        "last_meaningful_hash": meaningful_hash,
        "event_date": report.event.event_date,
        "event_url": report.event.event_url,
    }
    return _write_state_json("sent_reports.json", payload)


def _load_state_json(filename: str) -> dict[str, Any] | None:
    ensure_runtime_dirs()
    target = get_paths().runtime_state_dir / filename
    if not target.exists():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def _write_state_json(filename: str, payload: dict[str, Any]) -> Path:
    ensure_runtime_dirs()
    target = get_paths().runtime_state_dir / filename
    target.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    return target
