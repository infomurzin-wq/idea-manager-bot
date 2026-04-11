from __future__ import annotations

from pathlib import Path

from idea_manager_bot.project_registry import ProjectTarget


def _read_text_if_exists(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def load_project_context(project: ProjectTarget) -> str:
    root = project.inbox_dir.parents[1]
    chunks: list[str] = []

    readme = root / "README.md"
    if readme.exists():
        chunks.append(f"# Project README\n{_read_text_if_exists(readme)[:2500]}")

    for candidate_name in ("ideas.md", "current-system.md", "current-context.md", "first-questions.md"):
        candidate = project.inbox_dir.parent / candidate_name
        if candidate.exists():
            chunks.append(f"# Inbox Context: {candidate.name}\n{_read_text_if_exists(candidate)[:2000]}")

    return "\n\n".join(chunk for chunk in chunks if chunk).strip()
