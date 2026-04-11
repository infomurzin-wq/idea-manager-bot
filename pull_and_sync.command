#!/bin/zsh
set -e

SYNC_REPO_DIR="${SYNC_REPO_DIR:-$HOME/MYCODEX-sync-inbox}"
LOCAL_SYNC_ROOT="/Users/amur/Documents/MYCODEX/shared/99_sync-inbox"

if [ -d "$SYNC_REPO_DIR/.git" ]; then
  git -C "$SYNC_REPO_DIR" pull --ff-only
  mkdir -p "$LOCAL_SYNC_ROOT/incoming/ideas" "$LOCAL_SYNC_ROOT/incoming/contexts"
  rsync -a --ignore-existing "$SYNC_REPO_DIR/incoming/ideas/" "$LOCAL_SYNC_ROOT/incoming/ideas/"
  rsync -a --ignore-existing "$SYNC_REPO_DIR/incoming/contexts/" "$LOCAL_SYNC_ROOT/incoming/contexts/"
fi

cd /Users/amur/Documents/MYCODEX/idea-manager-bot
python3 scripts/sync_inbox.py
open -a Codex
