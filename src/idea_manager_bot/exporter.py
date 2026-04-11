from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path

from idea_manager_bot.config import Settings


class SyncExporter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return self.settings.sync_export_mode in {"filesystem", "github"}

    def export_record(self, payload: dict, entity_type: str, remote_id: str) -> tuple[bool, str]:
        if self.settings.sync_export_mode == "filesystem":
            return self._export_to_filesystem(payload, entity_type, remote_id)
        if self.settings.sync_export_mode == "github":
            return self._export_to_github(payload, entity_type, remote_id)
        return False, "sync export disabled"

    def _export_to_filesystem(self, payload: dict, entity_type: str, remote_id: str) -> tuple[bool, str]:
        if not self.settings.sync_export_dir:
            return False, "SYNC_EXPORT_DIR is not configured"

        target_dir = self.settings.sync_export_dir / "incoming" / f"{entity_type}s"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{remote_id}.json"
        payload = payload.copy()
        payload["remote_id"] = remote_id
        target_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True, str(target_path)

    def _export_to_github(self, payload: dict, entity_type: str, remote_id: str) -> tuple[bool, str]:
        if not self.settings.github_sync_repo or not self.settings.github_sync_token:
            return False, "GITHUB_SYNC_REPO or GITHUB_SYNC_TOKEN is not configured"

        payload = payload.copy()
        payload["remote_id"] = remote_id
        json_content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        encoded = base64.b64encode(json_content).decode("ascii")

        base_path = self.settings.github_sync_base_path.strip("/")
        relative_path = f"incoming/{entity_type}s/{remote_id}.json"
        if base_path:
            relative_path = f"{base_path}/{relative_path}"

        url = f"https://api.github.com/repos/{self.settings.github_sync_repo}/contents/{relative_path}"
        body = json.dumps(
            {
                "message": f"Add {entity_type} {remote_id}",
                "content": encoded,
                "branch": self.settings.github_sync_branch,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            method="PUT",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.settings.github_sync_token}",
                "Content-Type": "application/json",
                "User-Agent": "IdeaManagerBot/0.1",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                _ = response.read()
            return True, f"github://{self.settings.github_sync_repo}/{relative_path}"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            return False, f"GitHub HTTP {exc.code}: {detail[:400]}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)
