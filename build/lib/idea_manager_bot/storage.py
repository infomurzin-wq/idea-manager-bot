from __future__ import annotations

import json
import re
from urllib.parse import urlparse
from pathlib import Path
from uuid import uuid4

from idea_manager_bot.models import ContextRecord, IdeaComment, IdeaRecord, utc_now_iso
from idea_manager_bot.project_registry import ProjectTarget


class IdeaStorage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.ideas_dir = data_dir / "ideas"
        self.contexts_dir = data_dir / "contexts"
        self.files_dir = data_dir / "files"
        self.ideas_dir.mkdir(parents=True, exist_ok=True)
        self.contexts_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)

    def create_idea(
        self,
        project: ProjectTarget,
        source_type: str,
        raw_input: str,
        normalized_text: str,
        links: list[str],
        analysis: str,
        source_url: str | None = None,
        extracted_content: str = "",
        link_fetch_status: str = "not_applicable",
        link_fetch_error: str | None = None,
        audio_path: str | None = None,
        sync_export_status: str = "not_exported",
        sync_export_target: str | None = None,
    ) -> IdeaRecord:
        idea_id = self._build_idea_id(project.key)
        created_at = utc_now_iso()
        title = self._build_title(
            normalized_text or raw_input,
            source_url=source_url,
            extracted_content=extracted_content,
        )
        markdown_path = project.inbox_dir / f"{idea_id}.md"

        record = IdeaRecord(
            idea_id=idea_id,
            project_key=project.key,
            project_label=project.label,
            title=title,
            source_type=source_type,
            raw_input=raw_input,
            normalized_text=normalized_text,
            links=links,
            source_url=source_url,
            extracted_content=extracted_content,
            link_fetch_status=link_fetch_status,
            link_fetch_error=link_fetch_error,
            created_at=created_at,
            updated_at=created_at,
            analysis=analysis,
            storage_path=str(markdown_path),
            audio_path=audio_path,
            sync_export_status=sync_export_status,
            sync_export_target=sync_export_target,
        )
        self.save_record(record, project.inbox_dir)
        return record

    def create_context(
        self,
        project: ProjectTarget,
        source_type: str,
        raw_input: str,
        normalized_text: str,
        links: list[str],
        source_url: str | None = None,
        extracted_content: str = "",
        link_fetch_status: str = "not_applicable",
        link_fetch_error: str | None = None,
        audio_path: str | None = None,
        sync_export_status: str = "not_exported",
        sync_export_target: str | None = None,
    ) -> ContextRecord:
        context_id = self._build_context_id(project.key)
        created_at = utc_now_iso()
        title = self._build_title(
            normalized_text or raw_input,
            source_url=source_url,
            extracted_content=extracted_content,
        )
        markdown_path = project.context_dir / f"{context_id}.md"

        record = ContextRecord(
            context_id=context_id,
            project_key=project.key,
            project_label=project.label,
            title=title,
            source_type=source_type,
            raw_input=raw_input,
            normalized_text=normalized_text,
            links=links,
            source_url=source_url,
            extracted_content=extracted_content,
            link_fetch_status=link_fetch_status,
            link_fetch_error=link_fetch_error,
            created_at=created_at,
            storage_path=str(markdown_path),
            audio_path=audio_path,
            sync_export_status=sync_export_status,
            sync_export_target=sync_export_target,
        )
        self.save_context_record(record, project.context_dir)
        return record

    def save_record(self, record: IdeaRecord, target_dir: Path | None = None) -> None:
        json_path = self.ideas_dir / f"{record.idea_id}.json"
        json_path.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        markdown_target = Path(record.storage_path)
        if target_dir:
            markdown_target = target_dir / markdown_target.name
        markdown_target.parent.mkdir(parents=True, exist_ok=True)
        markdown_target.write_text(self._render_markdown(record), encoding="utf-8")

    def save_context_record(self, record: ContextRecord, target_dir: Path | None = None) -> None:
        json_path = self.contexts_dir / f"{record.context_id}.json"
        json_path.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        markdown_target = Path(record.storage_path)
        if target_dir:
            markdown_target = target_dir / markdown_target.name
        markdown_target.parent.mkdir(parents=True, exist_ok=True)
        markdown_target.write_text(self._render_context_markdown(record), encoding="utf-8")

    def load_record(self, idea_id: str) -> IdeaRecord | None:
        json_path = self.ideas_dir / f"{idea_id}.json"
        if not json_path.exists():
            return None
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        return IdeaRecord.from_dict(payload)

    def load_context_record(self, context_id: str) -> ContextRecord | None:
        json_path = self.contexts_dir / f"{context_id}.json"
        if not json_path.exists():
            return None
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        return ContextRecord.from_dict(payload)

    def list_records(self, project_key: str | None = None) -> list[IdeaRecord]:
        items: list[IdeaRecord] = []
        for path in sorted(self.ideas_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = IdeaRecord.from_dict(payload)
            if project_key and record.project_key != project_key:
                continue
            items.append(record)
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    def list_context_records(self, project_key: str | None = None) -> list[ContextRecord]:
        items: list[ContextRecord] = []
        for path in sorted(self.contexts_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            record = ContextRecord.from_dict(payload)
            if project_key and record.project_key != project_key:
                continue
            items.append(record)
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def add_comment(self, record: IdeaRecord, text: str, author: str) -> IdeaRecord:
        record.comments.append(IdeaComment(created_at=utc_now_iso(), author=author, text=text))
        record.updated_at = utc_now_iso()
        self.save_record(record)
        return record

    def save_binary_file(self, idea_id: str, extension: str, content: bytes) -> Path:
        safe_extension = extension.lstrip(".") or "bin"
        target = self.files_dir / f"{idea_id}.{safe_extension}"
        target.write_bytes(content)
        return target

    @staticmethod
    def extract_links(text: str) -> list[str]:
        return re.findall(r"https?://\S+", text)

    @staticmethod
    def _build_idea_id(project_key: str) -> str:
        short = project_key.replace("-", "")[:5]
        return f"{short}-{uuid4().hex[:8]}"

    @staticmethod
    def _build_context_id(project_key: str) -> str:
        short = project_key.replace("-", "")[:5]
        return f"ctx-{short}-{uuid4().hex[:8]}"

    @staticmethod
    def _build_title(text: str, source_url: str | None = None, extracted_content: str = "") -> str:
        line = " ".join(text.strip().split())
        if not line:
            return "Идея без заголовка"

        is_url_like = bool(re.match(r"^https?://", line))
        if is_url_like:
            host = ""
            if source_url:
                host = urlparse(source_url).netloc.replace("www.", "")
            summary = " ".join(extracted_content.strip().split())[:70] if extracted_content else ""
            if summary:
                label = f"{host}: {summary}" if host else summary
                return label if len(label) <= 80 else f"{label[:77]}..."
            if host:
                return f"{host}: ссылка"
            return "Ссылка без описания"

        if len(line) <= 80:
            return line
        return f"{line[:77]}..."

    @staticmethod
    def _render_markdown(record: IdeaRecord) -> str:
        links = "\n".join(f"- {item}" for item in record.links) if record.links else "- ссылок нет"
        comments = (
            "\n".join(
                f"- {comment.created_at} | {comment.author}: {comment.text}"
                for comment in record.comments
            )
            if record.comments
            else "- комментариев пока нет"
        )
        return (
            f"# {record.title}\n\n"
            f"- Idea ID: `{record.idea_id}`\n"
            f"- Project: `{record.project_key}`\n"
            f"- Source type: `{record.source_type}`\n"
            f"- Status: `{record.status}`\n"
            f"- Source URL: `{record.source_url or 'n/a'}`\n"
            f"- Link fetch status: `{record.link_fetch_status}`\n"
            f"- Link fetch error: `{record.link_fetch_error or 'n/a'}`\n"
            f"- Sync export status: `{record.sync_export_status}`\n"
            f"- Sync export target: `{record.sync_export_target or 'n/a'}`\n"
            f"- Created at: `{record.created_at}`\n"
            f"- Updated at: `{record.updated_at}`\n\n"
            "## Raw Input\n"
            f"{record.raw_input}\n\n"
            "## Normalized Text\n"
            f"{record.normalized_text or 'Нет нормализованного текста.'}\n\n"
            "## Links\n"
            f"{links}\n\n"
            "## Extracted Content\n"
            f"{record.extracted_content or 'Извлечённого содержимого нет.'}\n\n"
            "## Analysis\n"
            f"{record.analysis or 'Анализ пока отсутствует.'}\n\n"
            "## Comments\n"
            f"{comments}\n"
        )

    @staticmethod
    def _render_context_markdown(record: ContextRecord) -> str:
        links = "\n".join(f"- {item}" for item in record.links) if record.links else "- ссылок нет"
        return (
            f"# {record.title}\n\n"
            f"- Context ID: `{record.context_id}`\n"
            f"- Project: `{record.project_key}`\n"
            f"- Source type: `{record.source_type}`\n"
            f"- Source URL: `{record.source_url or 'n/a'}`\n"
            f"- Link fetch status: `{record.link_fetch_status}`\n"
            f"- Link fetch error: `{record.link_fetch_error or 'n/a'}`\n"
            f"- Sync export status: `{record.sync_export_status}`\n"
            f"- Sync export target: `{record.sync_export_target or 'n/a'}`\n"
            f"- Created at: `{record.created_at}`\n\n"
            "## Raw Input\n"
            f"{record.raw_input}\n\n"
            "## Normalized Text\n"
            f"{record.normalized_text or 'Нет нормализованного текста.'}\n\n"
            "## Links\n"
            f"{links}\n\n"
            "## Extracted Content\n"
            f"{record.extracted_content or 'Извлечённого содержимого нет.'}\n"
        )
