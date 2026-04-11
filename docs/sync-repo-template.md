# Sync Repo Template

Создай отдельный GitHub-репозиторий, например:

`mycodex-sync-inbox`

Минимальная структура репозитория:

```text
incoming/
  ideas/
  contexts/
processed/
  ideas/
  contexts/
README.md
```

## Зачем отдельный репозиторий

- не смешивает sync-поток с основным `MYCODEX`
- проще давать Railway доступ только к одной зоне
- проще отлаживать входящие JSON

## README для sync repo

Можно положить такой текст:

```md
# MYCODEX Sync Inbox

Этот репозиторий используется как обменный слой между Telegram-ботом и локальным MYCODEX.

- `incoming/ideas` — новые идеи
- `incoming/contexts` — новый контекст
- `processed` — опционально, если позже захочется отражать обработку и в облаке
```

## Что будет писать бот

Бот будет создавать JSON-файлы в:

- `incoming/ideas/*.json`
- `incoming/contexts/*.json`

Каждый JSON содержит:

- `entity_type`
- `project_key`
- `title`
- `raw_input`
- `normalized_text`
- `source_type`
- `created_at`
- `source_url`
- `links`
- `extracted_content`
- `link_fetch_status`
- `link_fetch_error`

Для идей дополнительно может быть:

- `analysis`

## Как это подтянется на Mac

Launcher `pull_and_sync.command`:

1. делает `git pull` этого репозитория;
2. копирует `incoming/ideas` и `incoming/contexts` в локальный `shared/99_sync-inbox`;
3. запускает `sync_inbox.py`;
4. открывает Codex.
