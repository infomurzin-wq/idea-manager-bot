from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class IdeaComment:
    created_at: str
    author: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "IdeaComment":
        return cls(**payload)


@dataclass
class IdeaRecord:
    idea_id: str
    project_key: str
    project_label: str
    title: str
    source_type: str
    raw_input: str
    normalized_text: str
    links: list[str]
    created_at: str
    updated_at: str
    source_url: str | None = None
    extracted_content: str = ""
    link_fetch_status: str = "not_applicable"
    link_fetch_error: str | None = None
    status: str = "new"
    analysis: str = ""
    storage_path: str = ""
    audio_path: str | None = None
    sync_export_status: str = "not_exported"
    sync_export_target: str | None = None
    comments: list[IdeaComment] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["comments"] = [comment.to_dict() for comment in self.comments]
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "IdeaRecord":
        payload = payload.copy()
        payload["comments"] = [IdeaComment.from_dict(item) for item in payload.get("comments", [])]
        return cls(**payload)


@dataclass
class ContextRecord:
    context_id: str
    project_key: str
    project_label: str
    title: str
    source_type: str
    raw_input: str
    normalized_text: str
    links: list[str]
    created_at: str
    storage_path: str
    source_url: str | None = None
    extracted_content: str = ""
    link_fetch_status: str = "not_applicable"
    link_fetch_error: str | None = None
    audio_path: str | None = None
    sync_export_status: str = "not_exported"
    sync_export_target: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "ContextRecord":
        return cls(**payload)
