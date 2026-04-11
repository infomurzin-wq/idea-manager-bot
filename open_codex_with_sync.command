#!/bin/zsh
set -e

cd /Users/amur/Documents/MYCODEX/idea-manager-bot
python3 scripts/sync_inbox.py
open -a Codex
