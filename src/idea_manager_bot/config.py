from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    openai_api_key: str | None
    openai_model: str
    workspace_root: Path
    bot_data_dir: Path
    sync_export_mode: str
    sync_export_dir: Path | None
    github_sync_repo: str | None
    github_sync_branch: str
    github_sync_token: str | None
    github_sync_base_path: str
    t_invest_token: str | None
    t_invest_account_id: str | None
    pma_ops_api_base: str | None = None
    pma_ops_hmac_secret: str | None = None
    pma_operator_user_id: int | None = None
    pma_operator_chat_id: int | None = None


def load_settings() -> Settings:
    load_dotenv()

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    workspace_root = Path(
        os.getenv("WORKSPACE_ROOT", "/Users/amur/Documents/MYCODEX")
    ).expanduser().resolve()
    bot_data_dir = Path(
        os.getenv("BOT_DATA_DIR", str(workspace_root / "idea-manager-bot" / "data"))
    ).expanduser().resolve()
    sync_export_dir_raw = os.getenv("SYNC_EXPORT_DIR", "").strip()
    sync_export_dir = Path(sync_export_dir_raw).expanduser().resolve() if sync_export_dir_raw else None

    return Settings(
        telegram_bot_token=telegram_bot_token,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
        workspace_root=workspace_root,
        bot_data_dir=bot_data_dir,
        sync_export_mode=os.getenv("SYNC_EXPORT_MODE", "disabled").strip(),
        sync_export_dir=sync_export_dir,
        github_sync_repo=os.getenv("GITHUB_SYNC_REPO") or None,
        github_sync_branch=os.getenv("GITHUB_SYNC_BRANCH", "main").strip(),
        github_sync_token=os.getenv("GITHUB_SYNC_TOKEN") or None,
        github_sync_base_path=os.getenv("GITHUB_SYNC_BASE_PATH", "").strip(),
        t_invest_token=os.getenv("T_INVEST_TOKEN") or None,
        t_invest_account_id=os.getenv("T_INVEST_ACCOUNT_ID") or None,
        pma_ops_api_base=os.getenv("PMA_OPS_API_BASE") or None,
        pma_ops_hmac_secret=os.getenv("PMA_OPS_HMAC_SECRET") or None,
        pma_operator_user_id=_optional_int(os.getenv("PMA_OPERATOR_USER_ID")),
        pma_operator_chat_id=_optional_int(os.getenv("PMA_OPERATOR_CHAT_ID")),
    )


def _optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError as exc:
        raise RuntimeError("Expected numeric Telegram operator id") from exc
