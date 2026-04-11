# Sync Architecture

## Цель

Сделать так, чтобы Telegram-бот мог жить в облаке `24/7`, а локальный `MYCODEX` на Mac автоматически подтягивал новые записи при открытии Codex.

## Архитектура

```text
Telegram -> Cloud Bot -> cloud sync inbox -> local sync on Mac -> MYCODEX folders
```

## Локальная часть

### 1. Exchange folder

Локальный путь:

`/Users/amur/Documents/MYCODEX/shared/99_sync-inbox`

Здесь есть:

- `incoming/ideas`
- `incoming/contexts`
- `processed/ideas`
- `processed/contexts`
- `failed`

### 2. Sync script

Скрипт:

`/Users/amur/Documents/MYCODEX/idea-manager-bot/scripts/sync_inbox.py`

Он:

- читает новые JSON-записи из `incoming`;
- проверяет проект;
- создаёт Markdown в нужной проектной папке;
- переносит исходный JSON в `processed`;
- при ошибке кладёт запись в `failed`.

### 3. Startup launcher

Файл:

`/Users/amur/Documents/MYCODEX/idea-manager-bot/open_codex_with_sync.command`

Поведение:

1. запускает sync-скрипт;
2. после этого открывает приложение `Codex`.

## Почему выбран такой путь

Прямой хук "когда пользователь открыл Codex" сейчас не гарантированно доступен как штатная интеграция.

Поэтому выбран безопасный и практичный путь:

- запускать Codex через локальный launcher;
- launcher сначала делает sync;
- затем открывает приложение.

Это даёт почти тот же пользовательский результат, но проще и надёжнее.

## Облачная часть, которую подключим дальше

На следующем этапе облачный бот должен писать JSON не прямо в локальный Mac, а в облачный `sync inbox`.

Практичный вариант:

1. Railway держит бот `24/7`.
2. Бот пишет входящие JSON в отдельный GitHub-репозиторий или в отдельную sync-папку репозитория.
3. Локальный Mac при запуске сначала делает `git pull`.
4. Затем запускается `sync_inbox.py`.

## Рекомендуемый следующий шаг

1. Протестировать локальный импорт вручную через один JSON-файл в `incoming`.
2. После этого добавить GitHub-слой как облачный транспорт.
3. Затем уже подключить Railway к этой схеме.
