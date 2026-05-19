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

## Bond Radar

Раздел `Облигации` использует тонкий bridge к проекту Bond Radar.

Локально можно оставить `BOND_RADAR_PROJECT_DIR`, `BOND_RADAR_SCRIPTS_DIR` и `BOND_RADAR_STORE_PATH` пустыми: тогда бот возьмёт проект и store по умолчанию:

```text
/Users/amur/Documents/MYCODEX/learning-programming/04_projects/bond-radar-bot/data/candidates_store.jsonl
```

Для Railway или другого окружения пути нужно задать явно, например:

```text
BOND_RADAR_PROJECT_DIR=/app/bond-radar-bot
BOND_RADAR_SCRIPTS_DIR=/app/bond-radar-bot/scripts
BOND_RADAR_STORE_PATH=/app/data/bond-radar/candidates_store.jsonl
```

Если `BOND_RADAR_SCRIPTS_DIR` пустой и внешний проект не найден, bridge использует bundled scripts из:

```text
src/idea_manager_bot/bond_radar_scripts
```

Если `BOND_RADAR_STORE_PATH` пустой и внешний проект не найден, store по умолчанию будет:

```text
$BOT_DATA_DIR/bond-radar/candidates_store.jsonl
```

Если такого файла ещё нет, бот при первом открытии `Облигации` скопирует стартовый snapshot из bundled seed. Это нужно для Railway: список кандидатов появляется сразу, а дальнейшие статусы `watchlist` / `rejected` сохраняются уже в volume и не перезатираются.

На текущем этапе это offline-store кандидатов. Live parsing Telegram-каналов и web-источников пока не включён в общий bot process.

Ручное добавление уже работает внутри общего бота: `Облигации -> Добавить вручную`. Пользователь отправляет текст поста, bridge вызывает bundled extractor/dedup, а найденные карточки попадают в тот же `candidates_store.jsonl`.
