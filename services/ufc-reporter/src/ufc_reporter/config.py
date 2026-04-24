from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_ROOT.parent
AUTOMATION_ROOT = SRC_ROOT.parent
PROJECT_ROOT = Path(os.getenv("UFC_REPORTER_PROJECT_ROOT", str(AUTOMATION_ROOT.parent))).expanduser().resolve()
RUNTIME_ROOT = Path(os.getenv("UFC_REPORTER_RUNTIME_ROOT", str(AUTOMATION_ROOT / "runtime"))).expanduser().resolve()


@dataclass(frozen=True)
class Paths:
    project_root: Path = PROJECT_ROOT
    automation_root: Path = AUTOMATION_ROOT
    reports_dir: Path = PROJECT_ROOT / "02_fight-analysis"
    runtime_root: Path = RUNTIME_ROOT
    runtime_cache_dir: Path = RUNTIME_ROOT / "cache"
    runtime_reports_dir: Path = RUNTIME_ROOT / "reports"
    runtime_state_dir: Path = RUNTIME_ROOT / "state"


def get_paths() -> Paths:
    return Paths()
