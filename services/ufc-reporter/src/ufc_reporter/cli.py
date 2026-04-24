from __future__ import annotations

import argparse
from pathlib import Path

from .config import get_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ufc_reporter",
        description="Stage 2 local pipeline for UFC weekly Markdown reports.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser(
        "bootstrap-markdown",
        help="Import an existing manual Markdown report into runtime snapshot JSON.",
    )
    bootstrap.add_argument("--input", required=True, help="Path to the source Markdown report.")
    bootstrap.add_argument(
        "--output",
        help="Optional path for the rendered Stage 2 Markdown. Defaults to runtime/reports/<slug>/rendered-report.md.",
    )

    render = subparsers.add_parser(
        "render",
        help="Render Markdown from a saved snapshot JSON or event slug.",
    )
    render.add_argument(
        "--snapshot",
        required=True,
        help="Snapshot path or event slug stored under runtime/reports/<event-slug>/report_snapshot.json.",
    )
    render.add_argument(
        "--output",
        help="Optional output path. Defaults to runtime/reports/<slug>/rendered-report.md.",
    )

    subparsers.add_parser(
        "paths",
        help="Show the important project and runtime paths used by the local pipeline.",
    )

    fetch_espn = subparsers.add_parser(
        "fetch-espn-event",
        help="Build a report snapshot directly from an ESPN UFC event page.",
    )
    fetch_espn.add_argument(
        "--event-url",
        required=True,
        help="Full ESPN fightcenter URL for the target event.",
    )
    fetch_espn.add_argument(
        "--output",
        help="Optional output path for the rendered Markdown.",
    )

    monitor = subparsers.add_parser(
        "monitor",
        help="Run the Stage 3 monitoring gate for baseline or incremental weekend cycles.",
    )
    monitor.add_argument(
        "--mode",
        required=True,
        choices=("baseline", "incremental"),
        help="Monitoring mode: Thursday baseline or Friday/Saturday incremental check.",
    )
    monitor.add_argument(
        "--send",
        default="none",
        choices=("none", "telegram"),
        help="Delivery target. Use telegram to send a summary message and the rendered Markdown report as a document.",
    )
    monitor.add_argument(
        "--weekend-only",
        action="store_true",
        help="Only open a reporting window if the nearest Saturday/Sunday has a UFC event.",
    )
    monitor.add_argument(
        "--reference-date",
        help="Optional YYYY-MM-DD override for deterministic monitoring runs and local testing.",
    )

    telegram_updates = subparsers.add_parser(
        "telegram-updates",
        help="Show recent Telegram chats that contacted the configured bot, useful for finding TELEGRAM_CHAT_ID.",
    )
    telegram_updates.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of recent Telegram updates to inspect.",
    )

    telegram_send_report = subparsers.add_parser(
        "telegram-send-report",
        help="Send an already-rendered Markdown report to Telegram without running the full monitor pipeline.",
    )
    telegram_send_report.add_argument(
        "--snapshot",
        required=True,
        help="Snapshot path or event slug stored under runtime/reports/<event-slug>/report_snapshot.json.",
    )
    telegram_send_report.add_argument(
        "--markdown",
        help="Optional Markdown path. Defaults to runtime/reports/<event-slug>/rendered-report.md.",
    )
    telegram_send_report.add_argument(
        "--kind",
        default="baseline",
        choices=("baseline", "incremental"),
        help="Delivery wording to use in the Telegram summary and document filename.",
    )

    railway_cron = subparsers.add_parser(
        "railway-cron",
        help="Run the Railway scheduled job: Thursday baseline, Friday/Saturday incremental, Telegram delivery.",
    )
    railway_cron.add_argument(
        "--send",
        default="telegram",
        choices=("none", "telegram"),
        help="Delivery target for the scheduled job. Defaults to telegram.",
    )
    railway_cron.add_argument(
        "--reference-date",
        help="Optional YYYY-MM-DD override for deterministic local testing.",
    )
    return parser


def _default_render_target(event_slug: str) -> Path:
    return get_paths().runtime_reports_dir / event_slug / "rendered-report.md"


def _handle_bootstrap(args: argparse.Namespace) -> int:
    from .manual_markdown import parse_manual_markdown_path
    from .rendering import render_report
    from .state_store import ensure_runtime_dirs, write_snapshot

    ensure_runtime_dirs()
    source_path = Path(args.input).resolve()
    report = parse_manual_markdown_path(source_path)
    snapshot_path = write_snapshot(report)
    markdown = render_report(report)
    output_path = Path(args.output).resolve() if args.output else _default_render_target(report.event.event_slug)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"snapshot={snapshot_path}")
    print(f"markdown={output_path}")
    return 0


def _handle_render(args: argparse.Namespace) -> int:
    from .rendering import render_report
    from .state_store import ensure_runtime_dirs, load_snapshot

    ensure_runtime_dirs()
    report = load_snapshot(args.snapshot)
    markdown = render_report(report)
    output_path = Path(args.output).resolve() if args.output else _default_render_target(report.event.event_slug)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"markdown={output_path}")
    return 0


def _handle_paths() -> int:
    paths = get_paths()
    print(f"project_root={paths.project_root}")
    print(f"automation_root={paths.automation_root}")
    print(f"reports_dir={paths.reports_dir}")
    print(f"runtime_root={paths.runtime_root}")
    return 0


def _handle_fetch_espn_event(args: argparse.Namespace) -> int:
    from .rendering import render_report
    from .sources.espn import build_report_from_event_url
    from .state_store import ensure_runtime_dirs, write_snapshot

    ensure_runtime_dirs()
    report = build_report_from_event_url(args.event_url)
    snapshot_path = write_snapshot(report)
    markdown = render_report(report)
    output_path = (
        Path(args.output).resolve()
        if args.output
        else _default_render_target(report.event.event_slug)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"snapshot={snapshot_path}")
    print(f"markdown={output_path}")
    return 0


def _handle_monitor(args: argparse.Namespace) -> int:
    from datetime import date

    from .monitoring import run_monitoring_cycle
    from .state_store import ensure_runtime_dirs

    ensure_runtime_dirs()
    reference_date = date.fromisoformat(args.reference_date) if args.reference_date else None
    result = run_monitoring_cycle(
        mode=args.mode,
        send=args.send,
        weekend_only=args.weekend_only,
        reference_date=reference_date,
    )
    print(f"status={result.status}")
    print(f"mode={result.mode}")
    print(f"reason={result.reason}")
    print(f"event_slug={result.event_slug}")
    print(f"event_date={result.event_date}")
    print(f"event_url={result.event_url}")
    print(f"snapshot={result.snapshot_path}")
    print(f"markdown={result.markdown_path}")
    print(f"changed={str(result.changed).lower()}")
    return 0


def _handle_telegram_updates(args: argparse.Namespace) -> int:
    from .state_store import ensure_runtime_dirs
    from .telegram import extract_chat_candidates, get_updates

    ensure_runtime_dirs()
    candidates = extract_chat_candidates(get_updates(limit=args.limit))
    if not candidates:
        print("No Telegram chat candidates found. Send /start to the bot first, then run this command again.")
        return 0
    for candidate in candidates:
        display_name = " ".join(
            part
            for part in (
                candidate["first_name"],
                candidate["last_name"],
                f"@{candidate['username']}" if candidate["username"] else "",
            )
            if part
        )
        print(f"chat_id={candidate['chat_id']}")
        print(f"type={candidate['type']}")
        print(f"name={display_name or 'n/a'}")
        print(f"last_text={candidate['last_text'] or 'n/a'}")
        print("")
    return 0


def _handle_telegram_send_report(args: argparse.Namespace) -> int:
    from .state_store import ensure_runtime_dirs, load_snapshot
    from .telegram import send_report_delivery

    ensure_runtime_dirs()
    report = load_snapshot(args.snapshot)
    markdown_path = (
        Path(args.markdown).resolve()
        if args.markdown
        else _default_render_target(report.event.event_slug)
    )
    send_report_delivery(report=report, markdown_path=markdown_path, report_kind=args.kind)
    print("status=sent")
    print(f"event_slug={report.event.event_slug}")
    print(f"markdown={markdown_path}")
    return 0


def _handle_railway_cron(args: argparse.Namespace) -> int:
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from .monitoring import run_monitoring_cycle
    from .state_store import ensure_runtime_dirs

    ensure_runtime_dirs()
    current_date = (
        date.fromisoformat(args.reference_date)
        if args.reference_date
        else datetime.now(ZoneInfo("Europe/Moscow")).date()
    )
    weekday = current_date.weekday()
    if weekday == 3:
        mode = "baseline"
    elif weekday in {4, 5}:
        mode = "incremental"
    else:
        print("status=skipped")
        print("mode=n/a")
        print("reason=Railway cron is only active on Thursday, Friday, and Saturday Moscow dates.")
        print(f"reference_date={current_date.isoformat()}")
        return 0

    result = run_monitoring_cycle(
        mode=mode,
        send=args.send,
        weekend_only=True,
        reference_date=current_date,
    )
    print(f"status={result.status}")
    print(f"mode={result.mode}")
    print(f"reason={result.reason}")
    print(f"event_slug={result.event_slug}")
    print(f"event_date={result.event_date}")
    print(f"event_url={result.event_url}")
    print(f"snapshot={result.snapshot_path}")
    print(f"markdown={result.markdown_path}")
    print(f"changed={str(result.changed).lower()}")
    print(f"reference_date={current_date.isoformat()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "bootstrap-markdown":
        return _handle_bootstrap(args)
    if args.command == "render":
        return _handle_render(args)
    if args.command == "paths":
        return _handle_paths()
    if args.command == "fetch-espn-event":
        return _handle_fetch_espn_event(args)
    if args.command == "monitor":
        return _handle_monitor(args)
    if args.command == "telegram-updates":
        return _handle_telegram_updates(args)
    if args.command == "telegram-send-report":
        return _handle_telegram_send_report(args)
    if args.command == "railway-cron":
        return _handle_railway_cron(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
