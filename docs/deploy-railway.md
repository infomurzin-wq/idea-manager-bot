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

## Discount Radar scheduled check

Для автоматической проверки скидок используй отдельный Railway scheduled service/job с командой:

```bash
idea-manager-bot discount-cron
```

В репозитории есть отдельный config-as-code файл для этого сервиса:

```text
deploy/railway-discount-cron.toml
```

Он задаёт:

- запуск через тот же `Dockerfile`;
- команду `idea-manager-bot discount-cron`;
- расписание `0 7 * * *`, то есть один запуск в день в 07:00 UTC / 10:00 по Москве;
- `restartPolicyType = NEVER`, чтобы cron-задача не перезапускалась как постоянный бот.

Этот entrypoint:

- не запускает Telegram polling;
- читает товары из `$BOT_DATA_DIR/discount-radar/products.json`;
- проверяет цены через best-effort Ozon parser;
- отправляет Telegram-сообщение только если цена стала ниже `reference_price`;
- молчит, если скидок нет.

Нужны те же env vars и тот же Railway Volume, что у основного бота:

- `TELEGRAM_BOT_TOKEN`
- `BOT_DATA_DIR=/app/data`
- подключённый volume к `/app/data`

Важно: scheduled job должен видеть тот же `BOT_DATA_DIR`, где основной бот хранит товары.

Для первой проверки можно временно добавить env var:

```text
DISCOUNT_CRON_DRY_RUN=1
```

В dry-run режиме cron выполнит проверку и запишет результат в Railway logs, но не отправит Telegram-сообщения. После успешной проверки удали эту переменную, чтобы включить реальные уведомления.

При настройке в Railway:

1. Создай отдельный service из того же GitHub repo.
2. Укажи config file path: `deploy/railway-discount-cron.toml`.
3. Подключи тот же volume к `/app/data`.
4. Добавь `TELEGRAM_BOT_TOKEN` и `BOT_DATA_DIR=/app/data`.
5. Для первого запуска временно добавь `DISCOUNT_CRON_DRY_RUN=1`.
6. Проверь Railway logs: процесс должен завершиться, а не остаться `Active`.
7. Удали `DISCOUNT_CRON_DRY_RUN`, чтобы включить реальные уведомления.
8. Оставь основной bot service без изменений, он продолжает запускаться обычной командой `idea-manager-bot`.

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
