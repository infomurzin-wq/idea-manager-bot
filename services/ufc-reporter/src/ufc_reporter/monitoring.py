from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import ReportSnapshot
from .normalize import compute_content_hash, report_payload_for_meaningful_hash
from .rendering import render_report
from .sources.espn import build_report_from_event_url
from .sources.espn_schedule import find_nearest_weekend_event, next_weekend_dates
from .state_store import (
    clear_active_weekend_event,
    ensure_runtime_dirs,
    load_active_weekend_event,
    load_last_sent_report,
    update_sent_report_state,
    write_active_weekend_event,
    write_rendered_markdown,
    write_snapshot,
)
from .telegram import send_report_delivery

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class MonitoringResult:
    status: str
    mode: str
    reason: str
    event_slug: str = "n/a"
    event_date: str = "n/a"
    event_url: str = "n/a"
    snapshot_path: str = "n/a"
    markdown_path: str = "n/a"
    changed: bool = False


def run_monitoring_cycle(
    *,
    mode: str,
    send: str = "none",
    weekend_only: bool = True,
    reference_date: date | None = None,
) -> MonitoringResult:
    ensure_runtime_dirs()
    current_date = reference_date or datetime.now(MOSCOW_TZ).date()
    if mode == "baseline":
        return _run_baseline(
            current_date=current_date,
            send=send,
            weekend_only=weekend_only,
        )
    if mode == "incremental":
        return _run_incremental(
            current_date=current_date,
            send=send,
            weekend_only=weekend_only,
        )
    raise ValueError(f"Unsupported monitor mode: {mode}")


def _run_baseline(*, current_date: date, send: str, weekend_only: bool) -> MonitoringResult:
    eligible_event = find_nearest_weekend_event(current_date) if weekend_only else None
    if weekend_only and not eligible_event:
        clear_active_weekend_event()
        return MonitoringResult(
            status="skipped",
            mode="baseline",
            reason="No UFC event is scheduled for the nearest Saturday/Sunday window.",
        )
    if eligible_event is None:
        raise ValueError("Non-weekend baseline mode is not implemented.")
    report = build_report_from_event_url(eligible_event.event_url)
    snapshot_path, markdown_path = _persist_report(report)
    meaningful_hash = _meaningful_hash(report)
    write_active_weekend_event(
        event_slug=report.event.event_slug,
        event_date=report.event.event_date,
        event_url=report.event.event_url,
        window_opened_at=_now_iso(),
        window_status="active",
    )
    _send_if_requested(send=send, report=report, markdown_path=markdown_path, report_kind="baseline")
    update_sent_report_state(
        event_slug=report.event.event_slug,
        report=report,
        meaningful_hash=meaningful_hash,
        report_kind="baseline",
        markdown_path=markdown_path,
        send_target=send,
    )
    return MonitoringResult(
        status="baseline_created",
        mode="baseline",
        reason="Weekend UFC event detected and baseline snapshot created.",
        event_slug=report.event.event_slug,
        event_date=report.event.event_date,
        event_url=report.event.event_url,
        snapshot_path=str(snapshot_path),
        markdown_path=str(markdown_path),
        changed=True,
    )


def _run_incremental(*, current_date: date, send: str, weekend_only: bool) -> MonitoringResult:
    active_event = load_active_weekend_event()
    if not active_event:
        return MonitoringResult(
            status="skipped",
            mode="incremental",
            reason="No active weekend monitoring window is open.",
        )
    if weekend_only and not _event_is_still_in_weekend_window(
        current_date=current_date,
        event_date=active_event["event_date"],
    ):
        clear_active_weekend_event()
        return MonitoringResult(
            status="skipped",
            mode="incremental",
            reason="Active weekend monitoring window is no longer eligible for the nearest weekend.",
            event_slug=active_event.get("event_slug", "n/a"),
            event_date=active_event.get("event_date", "n/a"),
            event_url=active_event.get("event_url", "n/a"),
        )
    report = build_report_from_event_url(active_event["event_url"])
    snapshot_path, markdown_path = _persist_report(report)
    previous_entry = load_last_sent_report(report.event.event_slug)
    meaningful_hash = _meaningful_hash(report)
    previous_hash = (
        previous_entry.get("last_meaningful_hash")
        if previous_entry
        else None
    ) or (
        previous_entry.get("last_sent_hash")
        if previous_entry
        else None
    )
    if previous_hash == meaningful_hash:
        return MonitoringResult(
            status="unchanged",
            mode="incremental",
            reason="Meaningful snapshot hash matches the last sent version; no update needed.",
            event_slug=report.event.event_slug,
            event_date=report.event.event_date,
            event_url=report.event.event_url,
            snapshot_path=str(snapshot_path),
            markdown_path=str(markdown_path),
        changed=False,
    )
    _send_if_requested(send=send, report=report, markdown_path=markdown_path, report_kind="incremental")
    update_sent_report_state(
        event_slug=report.event.event_slug,
        report=report,
        meaningful_hash=meaningful_hash,
        report_kind="incremental",
        markdown_path=markdown_path,
        send_target=send,
    )
    return MonitoringResult(
        status="changed",
        mode="incremental",
        reason="Snapshot differs from the last sent version.",
        event_slug=report.event.event_slug,
        event_date=report.event.event_date,
        event_url=report.event.event_url,
        snapshot_path=str(snapshot_path),
        markdown_path=str(markdown_path),
        changed=True,
    )


def _persist_report(report: ReportSnapshot) -> tuple[Path, Path]:
    snapshot_path = write_snapshot(report)
    markdown = render_report(report)
    markdown_path = write_rendered_markdown(report.event.event_slug, markdown, "rendered-report.md")
    return snapshot_path, markdown_path


def _event_is_still_in_weekend_window(*, current_date: date, event_date: str) -> bool:
    target_date = date.fromisoformat(event_date)
    saturday, sunday = next_weekend_dates(current_date)
    return target_date in {saturday, sunday}


def _now_iso() -> str:
    return datetime.now(MOSCOW_TZ).replace(microsecond=0).isoformat()


def _meaningful_hash(report: ReportSnapshot) -> str:
    payload = report_payload_for_meaningful_hash(report.to_dict())
    return compute_content_hash(payload)


def _send_if_requested(
    *,
    send: str,
    report: ReportSnapshot,
    markdown_path: Path,
    report_kind: str,
) -> None:
    if send == "none":
        return
    if send == "telegram":
        send_report_delivery(
            report=report,
            markdown_path=markdown_path,
            report_kind=report_kind,
        )
        return
    raise ValueError(f"Unsupported send target: {send}")
