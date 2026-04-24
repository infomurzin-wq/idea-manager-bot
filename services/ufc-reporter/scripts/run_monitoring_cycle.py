#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _add_src_to_path() -> None:
    script_dir = Path(__file__).resolve().parent
    src_dir = script_dir.parent / "src"
    sys.path.insert(0, str(src_dir))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stage 3 monitor runner for event-gated Thursday/Friday/Saturday UFC reporting."
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("baseline", "incremental"),
        help="Use baseline for Thursday and incremental for Friday/Saturday checks.",
    )
    parser.add_argument(
        "--send",
        default="none",
        choices=("none", "telegram"),
        help="Delivery target. Telegram is not wired yet, but the state is tracked for future Stage 4.",
    )
    parser.add_argument(
        "--weekend-only",
        action="store_true",
        help="Only run if the nearest Saturday/Sunday has a UFC event.",
    )
    parser.add_argument(
        "--reference-date",
        help="Optional YYYY-MM-DD override for local testing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _add_src_to_path()
    from ufc_reporter.cli import main as cli_main

    args = build_parser().parse_args(argv)
    cli_args = [
        "monitor",
        "--mode",
        args.mode,
        "--send",
        args.send,
    ]
    if args.weekend_only:
        cli_args.append("--weekend-only")
    if args.reference_date:
        cli_args.extend(["--reference-date", args.reference_date])
    return cli_main(cli_args)


if __name__ == "__main__":
    raise SystemExit(main())
