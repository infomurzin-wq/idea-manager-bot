# Env Setup

## Локальный режим

Используй:

`/Users/amur/Documents/MYCODEX/idea-manager-bot/.env.local.example`

Шаги:

1. Скопируй файл в `.env`
2. Заполни:
   - `TELEGRAM_BOT_TOKEN`
   - `OPENAI_API_KEY`
3. Оставь:
   - `SYNC_EXPORT_MODE=filesystem`
   - `SYNC_EXPORT_DIR=/Users/amur/Documents/MYCODEX/shared/99_sync-inbox`

В этом режиме бот сразу экспортирует входящие JSON в локальный sync inbox.

## Railway режим

Используй:

`/Users/amur/Documents/MYCODEX/idea-manager-bot/.env.railway.example`

В Railway нужно задать env vars вручную в UI.

Ключевые значения:

- `BOT_DATA_DIR=/app/data`
- `SYNC_EXPORT_MODE=github`
- `GITHUB_SYNC_REPO=yourname/mycodex-sync-inbox`
- `GITHUB_SYNC_BRANCH=main`
- `GITHUB_SYNC_TOKEN=...`

## Что выбрать на старте

Лучший порядок такой:

1. Локально проверить `.env.local`
2. После подтверждения логики перенести те же сценарии на Railway через `.env.railway`
