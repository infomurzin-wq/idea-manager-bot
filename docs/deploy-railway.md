# Deploy on Railway

## Что разворачиваем

На Railway будет жить Telegram-бот.

Он:

- принимает идеи и контекст;
- анализирует идеи;
- экспортирует входящие JSON в `sync inbox`;
- не зависит от того, включён ли твой Mac.

## Два режима экспорта

### 1. Filesystem

Подходит для локальной отладки или если бот работает рядом с общей папкой.

Переменные:

- `SYNC_EXPORT_MODE=filesystem`
- `SYNC_EXPORT_DIR=/some/path/to/sync-inbox`

### 2. GitHub

Подходит для Railway и схемы `cloud -> Mac sync`.

Переменные:

- `SYNC_EXPORT_MODE=github`
- `GITHUB_SYNC_REPO=owner/repo`
- `GITHUB_SYNC_BRANCH=main`
- `GITHUB_SYNC_TOKEN=...`
- `GITHUB_SYNC_BASE_PATH=` при необходимости

В этом режиме бот создаёт JSON-файлы через GitHub Contents API в папках:

- `incoming/ideas`
- `incoming/contexts`

## Railway env vars

Минимальный набор:

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `BOT_DATA_DIR=/app/data`
- `SYNC_EXPORT_MODE=github`
- `GITHUB_SYNC_REPO=owner/repo`
- `GITHUB_SYNC_BRANCH=main`
- `GITHUB_SYNC_TOKEN=...`

## Start command

Можно использовать:

```bash
idea-manager-bot
```

или

```bash
python -m idea_manager_bot.bot
```

## Локальная сторона

На Mac должен быть клон sync-репозитория, например:

`$HOME/MYCODEX-sync-inbox`

После этого запускай:

`/Users/amur/Documents/MYCODEX/idea-manager-bot/pull_and_sync.command`

Что делает launcher:

1. `git pull` для sync-репозитория
2. копирование новых JSON в локальный `shared/99_sync-inbox/incoming`
3. запуск `sync_inbox.py`
4. открытие Codex

## Результат

В боевом режиме поток будет таким:

1. Ты отправляешь запись в Telegram.
2. Railway-бот принимает её `24/7`.
3. Бот экспортирует JSON в GitHub sync repo.
4. Утром ты открываешь Codex через launcher.
5. Launcher делает pull и импорт.
6. Новые идеи и контекст уже лежат в локальном `MYCODEX`.
