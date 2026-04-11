# Launch Checklist

## 1. Telegram

- Создать бота через `@BotFather`
- Сохранить `TELEGRAM_BOT_TOKEN`

## 2. OpenAI

- Подготовить `OPENAI_API_KEY`
- Проверить, что ключ подходит для:
  - текстового анализа
  - транскрибации аудио

## 3. GitHub sync repo

- Создать отдельный репозиторий, например `mycodex-sync-inbox`
- Создать в нём папки:
  - `incoming/ideas`
  - `incoming/contexts`
  - `processed/ideas`
  - `processed/contexts`
- Создать GitHub token с доступом к этому репозиторию

## 4. Локальный Mac

- Клонировать sync repo, например в:
  - `$HOME/MYCODEX-sync-inbox`
- Проверить launcher:
  - `/Users/amur/Documents/MYCODEX/idea-manager-bot/pull_and_sync.command`
- При желании запускать Codex именно через этот launcher

## 5. Локальный тест бота

- Скопировать `.env.local.example` в `.env`
- Заполнить значения
- Создать venv:

```bash
cd /Users/amur/Documents/MYCODEX/idea-manager-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

- Запустить:

```bash
idea-manager-bot
```

- Проверить:
  - новая идея
  - новый контекст
  - ссылка как идея
  - ссылка как контекст
  - `summary`
  - `сделать из контекста идею`

## 6. Railway

- Создать новый сервис
- Подключить репозиторий с `idea-manager-bot`
- Заполнить env vars по `.env.railway.example`
- Start command:

```bash
idea-manager-bot
```

- После деплоя проверить:
  - бот отвечает в Telegram
  - JSON появляется в sync repo

## 7. Финальная проверка

- Отправить идею в Telegram
- Убедиться, что Railway записал JSON в sync repo
- На Mac запустить `pull_and_sync.command`
- Убедиться, что идея появилась в нужной папке `MYCODEX`
