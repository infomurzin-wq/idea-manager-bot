#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


WORKSPACE_ROOT = Path("/Users/amur/Documents/MYCODEX")
SYNC_ROOT = WORKSPACE_ROOT / "shared" / "99_sync-inbox"
INCOMING_IDEAS = SYNC_ROOT / "incoming" / "ideas"
INCOMING_CONTEXTS = SYNC_ROOT / "incoming" / "contexts"
PROCESSED_IDEAS = SYNC_ROOT / "processed" / "ideas"
PROCESSED_CONTEXTS = SYNC_ROOT / "processed" / "contexts"
FAILED_DIR = SYNC_ROOT / "failed"
LOCAL_SYNC_STATE = WORKSPACE_ROOT / "idea-manager-bot" / "data" / "local-sync-state.json"


PROJECT_PATHS = {
    "ufc-betting": {
        "idea_dir": WORKSPACE_ROOT / "ufc-betting" / "01_inbox" / "ideas",
        "context_dir": WORKSPACE_ROOT / "ufc-betting" / "01_inbox" / "context",
    },
    "venture-investing": {
        "idea_dir": WORKSPACE_ROOT / "venture-investing" / "01_inbox" / "ideas-cards",
        "context_dir": WORKSPACE_ROOT / "venture-investing" / "01_inbox" / "context-cards",
    },
    "learning-programming": {
        "idea_dir": WORKSPACE_ROOT / "learning-programming" / "01_inbox" / "ideas",
        "context_dir": WORKSPACE_ROOT / "learning-programming" / "01_inbox" / "context",
    },
    "bank-factoring-product": {
        "idea_dir": WORKSPACE_ROOT / "bank-factoring-product" / "01_inbox" / "ideas",
        "context_dir": WORKSPACE_ROOT / "bank-factoring-product" / "01_inbox" / "context",
    },
    "shared": {
        "idea_dir": WORKSPACE_ROOT / "shared" / "01_inbox" / "ideas",
        "context_dir": WORKSPACE_ROOT / "shared" / "01_inbox" / "context",
    },
}


@dataclass
class SyncStats:
    imported_ideas: int = 0
    imported_contexts: int = 0
    failed: int = 0


def main() -> None:
    ensure_dirs()
    stats = SyncStats()
    state = load_state()

    for path in sorted(INCOMING_IDEAS.glob("*.json")):
        if process_file(path, "idea", state):
            stats.imported_ideas += 1
        else:
            stats.failed += 1

    for path in sorted(INCOMING_CONTEXTS.glob("*.json")):
        if process_file(path, "context", state):
            stats.imported_contexts += 1
        else:
            stats.failed += 1

    save_state(state)
    print(
        f"Sync complete: ideas={stats.imported_ideas}, "
        f"contexts={stats.imported_contexts}, failed={stats.failed}"
    )


def ensure_dirs() -> None:
    for path in (
        INCOMING_IDEAS,
        INCOMING_CONTEXTS,
        PROCESSED_IDEAS,
        PROCESSED_CONTEXTS,
        FAILED_DIR,
        LOCAL_SYNC_STATE.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)

    for project_dirs in PROJECT_PATHS.values():
        project_dirs["idea_dir"].mkdir(parents=True, exist_ok=True)
        project_dirs["context_dir"].mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    if not LOCAL_SYNC_STATE.exists():
        return {"imported_files": [], "last_synced_at": None}
    return json.loads(LOCAL_SYNC_STATE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    state["last_synced_at"] = datetime.now(UTC).isoformat()
    LOCAL_SYNC_STATE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def process_file(path: Path, entity_type: str, state: dict) -> bool:
    if str(path) in state.get("imported_files", []):
        move_to_processed(path, entity_type)
        return True

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        project_key = payload["project_key"]
        if project_key not in PROJECT_PATHS:
            raise ValueError(f"Unknown project_key: {project_key}")

        target_path = build_target_path(payload, entity_type)
        markdown = render_markdown(payload, entity_type)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(markdown, encoding="utf-8")

        state.setdefault("imported_files", []).append(str(path))
        move_to_processed(path, entity_type)
        return True
    except Exception as exc:  # noqa: BLE001
        failed_path = FAILED_DIR / path.name
        error_note = FAILED_DIR / f"{path.stem}.error.txt"
        shutil.move(str(path), failed_path)
        error_note.write_text(str(exc), encoding="utf-8")
        return False


def move_to_processed(path: Path, entity_type: str) -> None:
    target_dir = PROCESSED_IDEAS if entity_type == "idea" else PROCESSED_CONTEXTS
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    if path.exists():
        shutil.move(str(path), target)


def build_target_path(payload: dict, entity_type: str) -> Path:
    project_key = payload["project_key"]
    title = slugify(payload.get("title") or payload.get("normalized_text") or payload.get("raw_input") or entity_type)
    created_at = normalize_date(payload.get("created_at"))
    suffix = payload.get("remote_id") or payload.get("id") or title[:16]
    filename = f"{created_at}-{suffix}.md"
    dir_key = "idea_dir" if entity_type == "idea" else "context_dir"
    return PROJECT_PATHS[project_key][dir_key] / filename


def render_markdown(payload: dict, entity_type: str) -> str:
    title = payload.get("title") or "Без названия"
    raw_input = payload.get("raw_input") or ""
    normalized_text = payload.get("normalized_text") or ""
    source_type = payload.get("source_type") or "unknown"
    project_key = payload.get("project_key") or "unknown"
    created_at = payload.get("created_at") or ""
    source_url = payload.get("source_url") or "n/a"
    link_fetch_status = payload.get("link_fetch_status") or "not_applicable"
    link_fetch_error = payload.get("link_fetch_error") or "n/a"
    extracted_content = payload.get("extracted_content") or "Извлечённого содержимого нет."
    links = payload.get("links") or []
    analysis = payload.get("analysis") or "Анализ не приложен."
    comments = payload.get("comments") or []

    links_block = "\n".join(f"- {item}" for item in links) if links else "- ссылок нет"
    comments_block = (
        "\n".join(
            f"- {item.get('created_at', '')} | {item.get('author', 'unknown')}: {item.get('text', '')}"
            for item in comments
        )
        if comments
        else "- комментариев нет"
    )

    header = "Idea" if entity_type == "idea" else "Context"
    body = (
        f"# {title}\n\n"
        f"- Imported entity: `{header.lower()}`\n"
        f"- Project: `{project_key}`\n"
        f"- Source type: `{source_type}`\n"
        f"- Source URL: `{source_url}`\n"
        f"- Link fetch status: `{link_fetch_status}`\n"
        f"- Link fetch error: `{link_fetch_error}`\n"
        f"- Created at: `{created_at}`\n\n"
        "## Raw Input\n"
        f"{raw_input}\n\n"
        "## Normalized Text\n"
        f"{normalized_text or 'Нет нормализованного текста.'}\n\n"
        "## Links\n"
        f"{links_block}\n\n"
        "## Extracted Content\n"
        f"{extracted_content}\n"
    )
    if entity_type == "idea":
        body += (
            "\n## Analysis\n"
            f"{analysis}\n\n"
            "## Comments\n"
            f"{comments_block}\n"
        )
    return body


def normalize_date(value: str | None) -> str:
    if not value:
        return datetime.now(UTC).strftime("%Y-%m-%d")
    return value[:10]


def slugify(text: str) -> str:
    cleaned = re.sub(r"\s+", "-", text.strip().lower())
    cleaned = re.sub(r"[^a-zа-я0-9\-_]+", "-", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip("-")
    return cleaned or "item"


if __name__ == "__main__":
    main()
