# UFC Automation

Этот раздел хранит архитектуру и рабочие артефакты для автоматизации weekly-подготовки к турнирам UFC.

## Что сюда входит

- ручной `Codex`-workflow для подготовки отчёта по ближайшему турниру;
- глобальный skill `ufc-weekly-report-prep` в `~/.codex/skills` для ручного запуска этого workflow;
- спецификация общего Python-pipeline, который позже можно вынести на `Railway`;
- шаблоны итоговых отчётов;
- логика `event-gated baseline + diff monitoring` для четверга, пятницы и субботы.

## Фазы проекта

### Фаза 1. Ручной skill внутри Codex

Цель:
- вручную запускать сбор отчёта по ближайшему турниру;
- получить один стабильный Markdown-отчёт в структуре проекта;
- проверить, что поля данных и формат отчёта действительно подходят под betting-workflow.

Результат:
- рабочий `skill`/ручной сценарий;
- общий формат данных и отчёта;
- тест на одном ближайшем или одном недавнем турнире.

### Фаза 2. Общий Python-движок

Цель:
- вынести сбор данных в повторно используемые модули и CLI-команды;
- добавить нормализацию, runtime snapshots, кэш и state;
- подключить secondary source adapter для moneyline без ручного копирования коэффициентов;
- зафиксировать Markdown как единственный обязательный итоговый формат для pipeline.

Результат:
- локально запускаемый pipeline без ручного копирования данных;
- подготовка к внешнему деплою.

### Фаза 3. Event-Gated Monitoring

Цель:
- научить pipeline открывать weekly monitoring window только под ближайший weekend event;
- сохранять active window state и не слать повторяющиеся апдейты без meaningful change.

Результат:
- в четверг в `10:00 Europe/Moscow` система сначала проверяет, есть ли UFC-турнир в ближайшую субботу или воскресенье;
- если weekend event есть, в четверг уходит baseline-отчёт, а в пятницу и субботу в `10:00 Europe/Moscow` уходят только meaningful changes;
- если weekend event нет, цикл этой недели не открывается, и система ждёт следующего четверга.

Текущий статус:
- local monitor уже реализован и smoke-tested с Telegram;
- active weekend window хранится в runtime state;
- dedup сейчас опирается на `meaningful_hash`, чтобы не реагировать на микрошум в proxy totals.

### Фаза 4. Telegram-доставка

Цель:
- научить pipeline отправлять полный baseline-отчёт и diff-обновления во внешний канал.
- использовать уже существующего Telegram-бота пользователя, а не создавать отдельного UFC-only бота.

Результат:
- baseline и updates доходят в личный Telegram-чат пользователя;
- полный Markdown-отчёт отправляется как `.md` файл;
- короткое summary или diff отправляется отдельным сообщением.

### Фаза 5. Railway automation

Цель:
- перенести тот же pipeline во внешнюю always-on среду.

Результат:
- weekly monitoring работает независимо от включённого компьютера.

## Основной документ

- [ufc-reporting-blueprint.md](/Users/amur/Documents/MYCODEX/ufc-betting/07_automation/specs/ufc-reporting-blueprint.md)
- [stage1-manual-skill-runbook.md](/Users/amur/Documents/MYCODEX/ufc-betting/07_automation/specs/stage1-manual-skill-runbook.md)
- `Stage 2` runtime now lives under `07_automation/src`, `07_automation/scripts`, and `07_automation/runtime`

## Шаблон отчёта

- [weekly-monitoring-report-template.md](/Users/amur/Documents/MYCODEX/ufc-betting/07_automation/templates/weekly-monitoring-report-template.md)

## Текущие команды

Переходный запуск из уже собранного ручного отчёта:

```bash
python 07_automation/scripts/run_manual_report.py \
  --input-markdown 02_fight-analysis/<report>.md
```

Прямой рендер из runtime snapshot:

```bash
PYTHONPATH=07_automation/src python -m ufc_reporter.cli render --snapshot <event-slug>
```

Прямой Stage 2 direct-source запуск из ESPN:

```bash
PYTHONPATH=07_automation/src python -m ufc_reporter.cli fetch-espn-event \
  --event-url https://www.espn.com/mma/fightcenter/_/id/<event-id>/league/ufc
```

Что делает эта команда сейчас:

- карточка турнира и последние 5 боёв идут из `ESPN`;
- если `ESPN` отдаёт неполную карту, missing bouts добираются из `UFC.com event page`;
- moneyline автоматически обогащается из `MMAOddsBreaker opening odds`, если статья по ивенту найдена через WordPress API;
- `ТБ 1.5` и `ТБ 2.5` тянутся из `Polymarket UFC index` как market-implied decimal odds;
- важно: totals сейчас не sportsbook, а prediction-market proxy.

Event-gated monitoring baseline:

```bash
PYTHONPATH=07_automation/src python -m ufc_reporter.cli monitor \
  --mode baseline \
  --weekend-only
```

Event-gated monitoring incremental:

```bash
PYTHONPATH=07_automation/src python -m ufc_reporter.cli monitor \
  --mode incremental \
  --weekend-only
```

Что делает monitor сейчас:

- в baseline-режиме ищет ближайший eligible UFC event на ближайшие выходные;
- если event найден, создаёт baseline snapshot и открывает `active_weekend_event.json`;
- в incremental-режиме продолжает только уже открытую weekend window;
- сравнивает не raw `content_hash`, а `meaningful_hash`, чтобы micro-moves в `Polymarket` totals не считались полноценным update сами по себе;
- при `--send telegram` отправляет короткое summary и полный Markdown-отчёт как `.md` document.

Telegram delivery требует env-переменные:

```bash
TELEGRAM_BOT_TOKEN=<existing-personal-bot-token>
TELEGRAM_CHAT_ID=<personal-chat-id>
```

Основной способ получить `TELEGRAM_CHAT_ID`: написать существующему `idea-manager-bot` команду `/myid`.

Fallback-способ после `/start` боту:

```bash
PYTHONPATH=07_automation/src TELEGRAM_BOT_TOKEN=<existing-personal-bot-token> \
  python -m ufc_reporter.cli telegram-updates
```

Если существующий бот уже работает через webhook или активный polling, `telegram-updates` может быть недоступен или пустым. В этом случае `TELEGRAM_CHAT_ID` нужно взять из логов или хранилища самого бота после твоего `/start`.

Smoke-test отправки уже собранного отчёта:

```bash
PYTHONPATH=07_automation/src \
TELEGRAM_BOT_TOKEN=<existing-personal-bot-token> \
TELEGRAM_CHAT_ID=<personal-chat-id> \
python -m ufc_reporter.cli telegram-send-report \
  --snapshot ufc-fight-night-sterling-vs-zalal
```

Текущий статус:

- `telegram.py` реализует `sendMessage` и `sendDocument` через Telegram Bot API;
- `monitor --send telegram` отправляет summary message и `.md` document;
- личный `chat_id` получен через `/myid`: `443939869`;
- `telegram-updates` остаётся fallback-путём, но не основным способом;
- `telegram-send-report` отправляет уже готовый runtime Markdown без полного rebuild;
- реальный smoke test доставки выполнен успешно.

## Railway deployment

Railway запускает тот же CLI, что и локальная проверка, но через отдельную команду:

```bash
python -m ufc_reporter.cli railway-cron
```

Что делает `railway-cron`:

- в четверг по московской дате запускает `baseline`;
- в пятницу и субботу по московской дате запускает `incremental`;
- в остальные дни ничего не делает и печатает `status=skipped`;
- всегда использует `--weekend-only`;
- по умолчанию отправляет результат в Telegram.

Railway env vars:

```bash
TELEGRAM_BOT_TOKEN=<existing-personal-bot-token>
TELEGRAM_CHAT_ID=443939869
UFC_REPORTER_RUNTIME_ROOT=/data/ufc-reporter
```

Для корректной пятницы/субботы нужен persistent state. На Railway нужно подключить Volume и примонтировать его в `/data`, иначе `active_weekend_event.json` и `sent_reports.json` могут потеряться между запусками.

Railway schedule:

```text
0 7 * * 4,5,6
```

Это `10:00 Europe/Moscow`, потому что Railway cron обычно задаётся в UTC.

Railway service settings:

- repository: `infomurzin-wq/idea-manager-bot`;
- root directory: `services/ufc-reporter`;
- build: Dockerfile из `services/ufc-reporter/Dockerfile`;
- start command можно оставить default из Dockerfile: `python -m ufc_reporter.cli railway-cron`.

Локальная проверка Railway-команды:

```bash
PYTHONPATH=07_automation/src \
TELEGRAM_BOT_TOKEN=<existing-personal-bot-token> \
TELEGRAM_CHAT_ID=443939869 \
python -m ufc_reporter.cli railway-cron --reference-date 2026-04-23
```
