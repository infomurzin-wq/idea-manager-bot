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
        description="Stage 2 bridge: import a manual Markdown report into runtime snapshot JSON and re-render it."
    )
    parser.add_argument(
        "--input-markdown",
        required=True,
        help="Path to the manual Stage 1 Markdown report.",
    )
    parser.add_argument(
        "--output",
        help="Optional output path for the rendered Markdown produced by the Stage 2 renderer.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _add_src_to_path()
    from ufc_reporter.cli import main as cli_main

    args = build_parser().parse_args(argv)
    cli_args = [
        "bootstrap-markdown",
        "--input",
        str(Path(args.input_markdown).resolve()),
    ]
    if args.output:
        cli_args.extend(["--output", str(Path(args.output).resolve())])
    return cli_main(cli_args)


if __name__ == "__main__":
    raise SystemExit(main())

