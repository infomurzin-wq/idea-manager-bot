# UFC Reporting Blueprint

## Цель

Собрать единый pipeline для подготовки betting-отчёта по ближайшему турниру UFC, который:

- вручную запускается в `Codex`;
- опирается не на один сайт, а на несколько источников;
- умеет сохранять baseline;
- умеет отправлять только meaningful updates в пятницу и субботу;
- позже без переписывания переносится на `Railway`.

На текущем этапе обязательный итоговый артефакт только один:

- `Markdown`-отчёт.

PDF может существовать как вспомогательный экспорт, но больше не считается частью core-scope для `Stage 2`.

## Рабочий сценарий

Текущий целевой ритм:

- `четверг в 10:00 Europe/Moscow` — сначала проверить, есть ли ближайший UFC-турнир в ближайшую `субботу` или `воскресенье`;
- если такого турнира нет, monitoring cycle в эту неделю не открывается, и система ждёт следующего четверга;
- если такой турнир есть, четверг становится baseline-run для этого конкретного ивента;
- `пятница в 10:00 Europe/Moscow` — запускать incremental check только если в четверг была открыта активная monitoring window;
- `суббота в 10:00 Europe/Moscow` — запускать incremental check только если monitoring window всё ещё активна для ближайшего weekend event.

Иными словами, weekly-monitoring должен быть `event-gated`, а не просто календарно-еженедельным.

## Источники данных

### Приоритет по источникам

Карточка турнира:
- `ESPN MMA` — основной источник;
- `UFC.com` — резерв на случай проблем с карточкой;
- `Tapology` — fallback.

Moneyline:
- `MMAOddsBreaker opening odds` — текущий secondary source для Stage 2;
- later: можно заменить или дополнить более стабильным market source, если понадобится closing line или totals.

Totals:
- `Polymarket UFC index` — текущий Stage 2 source для `ТБ 1.5 / ТБ 2.5`;
- важно: это не классический букмекерский рынок, а market-implied proxy из prediction market.

История бойца за последние 5 боёв:
- `ESPN MMA` — основной источник;
- `Tapology` — fallback и cross-check;
- `Sherdog` — опциональный резерв, но не как главный источник.

Сводная статистика бойца:
- `Tapology` — основной источник;
- `ESPN MMA` — частичный резерв;
- при необходимости позже можно расширить расчёт локально из полной истории.

Предбоевые сигналы и новости:
- свежий веб-поиск по надёжным MMA-источникам;
- официальные заявления бойцов, тренеров, UFC или менеджмента;
- крупные профильные медиа;
- прямые соцсигналы только как дополнительный источник, не как единственная опора.

### Почему не один сайт

Нужный тебе набор полей распадается на несколько слоёв:

- upcoming event card;
- последние 5 боёв;
- промоушен/лига;
- методы побед и поражений;
- moneyline и totals;
- агрегированная сводка по бойцу.

Один сайт может временно лечь или отдать неполные данные. Поэтому архитектура должна быть `source-agnostic`.

## Данные, которые должны быть в отчёте

### По турниру

- название турнира;
- дата турнира;
- ссылка на основной источник карточки;
- список боёв.

### По каждому бою

- боец `A`;
- боец `B`;
- статус боя;
- весовая категория, если доступна;
- признак main card / prelims, если доступно.
- коэффициент на бойца `A` в decimal format, если доступен;
- коэффициент на бойца `B` в decimal format, если доступен;
- коэффициент на `ТБ 1.5`, если доступен;
- коэффициент на `ТБ 2.5`, если доступен;
- русский аналитический комментарий по бою.
- краткая сводка, есть ли на стороне одного из бойцов существенный предбоевой сигнал.

### По каждому бойцу

- полное имя;
- record `wins-losses-draws`, если доступно;
- последние 5 боёв;
- сводка методов побед;
- сводка методов поражений;
- список источников, из которых собраны данные;
- признак неполноты данных.
- русский аналитический комментарий.
- блок существенных предбоевых сигналов.

### По каждому из последних 5 боёв

- дата;
- соперник;
- результат: `W/L/D/NC`;
- метод;
- раунд;
- время, если доступно;
- промоушен/лига;
- event name.

Результат в финальном Markdown должен визуально размечаться как:

- `🟩 W`
- `🟥 L`
- `🟨 D`
- `⬜ NC`

## Канонические сущности

### `EventSnapshot`

- `event_id`
- `event_name`
- `event_date`
- `event_slug`
- `event_url`
- `source`
- `bouts[]`

### `BoutSnapshot`

- `bout_id`
- `fighter_a_name`
- `fighter_b_name`
- `fighter_a_slug`
- `fighter_b_slug`
- `weight_class`
- `card_segment`
- `status`
- `fighter_a_moneyline_decimal`
- `fighter_b_moneyline_decimal`
- `over_1_5_decimal`
- `over_2_5_decimal`
- `bout_commentary_ru`

### `FighterSnapshot`

- `fighter_slug`
- `fighter_name`
- `record_summary`
- `last_five[]`
- `summary_stats`
- `sources[]`
- `data_quality`
- `fighter_commentary_ru`
- `pre_fight_signals[]`

### `FightResultEntry`

- `fight_date`
- `opponent`
- `result`
- `method`
- `round`
- `time`
- `promotion`
- `event_name`

### `FighterSummary`

- `wins_total`
- `losses_total`
- `draws_total`
- `wins_by_ko_tko`
- `wins_by_submission`
- `wins_by_decision`
- `wins_by_other`
- `losses_by_ko_tko`
- `losses_by_submission`
- `losses_by_decision`
- `losses_by_other`

### `ReportSnapshot`

- `event`
- `fighters`
- `generated_at`
- `report_version`
- `content_hash`

### `SentReportState`

- `event_slug`
- `last_sent_hash`
- `last_sent_at`
- `last_sent_kind`
- `last_sent_path`

### `DiffResult`

- `is_changed`
- `changed_fighters[]`
- `changed_bouts[]`
- `change_summary[]`

### `PreFightSignal`

- `signal_type`
- `summary_ru`
- `impact_note_ru`
- `source_url`
- `source_name`
- `published_date`
- `confidence`

## Целевая структура проекта

Ниже не текущее состояние, а целевая структура после поэтапной реализации:

```text
ufc-betting/
├── 02_fight-analysis/
│   └── YYYY-MM-DD-<event-slug>.md
├── 07_automation/
│   ├── README.md
│   ├── specs/
│   │   └── ufc-reporting-blueprint.md
│   ├── templates/
│   │   └── weekly-monitoring-report-template.md
│   ├── scripts/
│   │   ├── run_manual_report.py
│   │   └── run_monitoring_cycle.py
│   ├── src/
│   │   └── ufc_reporter/
│   │       ├── cli.py
│   │       ├── config.py
│   │       ├── models.py
│   │       ├── normalize.py
│   │       ├── diffing.py
│   │       ├── rendering.py
│   │       ├── telegram.py
│   │       ├── state_store.py
│   │       └── sources/
│   │           ├── espn.py
│   │           ├── mmaoddsbreaker.py
│   │           ├── tapology.py
│   │           ├── ufc_official.py
│   │           └── sherdog.py
│   └── runtime/
│       ├── cache/
│       ├── reports/
│       └── state/
```

## Скрипты и их роль

### Фаза 1. Ручной запуск в Codex

`run_manual_report.py`

Назначение:
- на переходном этапе импортировать текущий ручной Markdown-отчёт в канонический snapshot;
- сохранить JSON snapshot в `07_automation/runtime/reports`;
- рендерить Markdown уже через локальный Python renderer.

Вход:
- `--event upcoming | <event-slug>`
- `--fighters-limit`
- `--sources`

Выход:
- готовый Markdown-отчёт;
- JSON snapshot;
- короткий summary в stdout.

### Текущее состояние Stage 2

Сейчас уже реализовано:

- `ESPN` как primary source для event card и fighter history;
- `UFC.com` как fallback card source;
- `MMAOddsBreaker` как secondary source adapter для opening moneyline;
- `Polymarket` как totals source для `ТБ 1.5 / ТБ 2.5`;
- автоматическая конвертация american odds в `decimal`;
- merge коэффициентов и fallback-card данных в текущие `BoutSnapshot` без ручной правки отчёта.

Что пока не реализовано:

- sportsbook-grade источник для `ТБ 1.5` и `ТБ 2.5`;
- более сильный внешний news layer beyond deterministic signals.

### Фаза 2. Мониторинг изменений

`run_monitoring_cycle.py`

Назначение:
- собрать новую версию отчёта;
- сравнить её с последней отправленной версией;
- при изменениях отправить diff или full report;
- обновить state.

Вход:
- `--mode baseline|incremental`
- `--send telegram|none`
- `--event upcoming`
- `--weekend-only true`

### Внутренние CLI-команды

```bash
python -m ufc_reporter.cli report --event upcoming
python -m ufc_reporter.cli monitor --mode baseline --weekend-only
python -m ufc_reporter.cli monitor --mode incremental --weekend-only
```

## Логика отправки

### Четверг

- сначала определить, есть ли ближайший UFC event в ближайшую субботу или воскресенье;
- если подходящего weekend event нет, завершать цикл без baseline, без Telegram и без открытия active window;
- если подходящий event есть:
  - собрать baseline;
  - отправить полный отчёт;
  - сохранить `last_sent_hash`;
  - открыть active monitoring window для конкретного `event_slug` и `event_date`.

### Пятница и суббота

- сначала проверить, есть ли открытая active monitoring window;
- если active window нет, завершать цикл без попытки собирать отчёт;
- если active window есть, дополнительно проверить, что её `event_date` всё ещё относится к ближайшим выходным;
- после этого собирать fresh snapshot;
- сравнивать не с четвергом как датой, а с `последней отправленной версией`;
- если hash и change set совпадают, ничего не отправлять;
- если есть meaningful change, отправлять update и обновлять `last_sent_hash`.

## Что считается meaningful change

- изменился список боёв;
- изменился статус боя;
- изменился один из последних 5 боёв бойца;
- обновилась сводная статистика бойца;
- обновились коэффициенты moneyline или `ТБ 1.5 / ТБ 2.5`;
- появился, исчез или изменился существенный предбоевой сигнал по бойцу;
- улучшилась полнота данных;
- поменялся основной источник из-за fallback.

Не считать изменением:
- новое время генерации отчёта;
- перестановку полей без фактической разницы;
- косметические изменения форматирования Markdown.

## State и runtime-артефакты

### `runtime/cache/`

Кэш сырых ответов и промежуточных нормализованных данных, чтобы:

- не дёргать сайты лишний раз;
- повторно использовать уже разобранные профили бойцов;
- упростить локальную отладку.

### `runtime/reports/`

- JSON snapshots;
- сгенерированные Markdown-копии;
- diff-артефакты.

### `runtime/state/`

Минимум:

- `sent_reports.json`
- `last_successful_run.json`
- `source_failures.json`
- `active_weekend_event.json`

`active_weekend_event.json` должен хранить:

- `event_slug`
- `event_date`
- `window_opened_at`
- `window_status`

Этот state нужен, чтобы пятница и суббота не стартовали вслепую, а продолжали только уже активированное в четверг weekend-monitoring окно.

## Формат Telegram-доставки

Доставка должна использовать уже существующего Telegram-бота пользователя, который живёт на Railway и используется для сбора идей/контекста.

Не создаём отдельного UFC-only бота на первом этапе. UFC pipeline должен переиспользовать существующий bot token и отправлять отчёты в личный Telegram chat пользователя через `TELEGRAM_CHAT_ID`.

Важно:

- бот сможет писать в личный чат только после того, как пользователь один раз начал диалог с ботом;
- `TELEGRAM_CHAT_ID` нужно получить и положить в env Railway;
- для получения `TELEGRAM_CHAT_ID` используется CLI-команда `telegram-updates`;
- если существующий бот работает через webhook или активный polling, `TELEGRAM_CHAT_ID` можно взять из логов или хранилища самого бота;
- для изолированного smoke test доставки используется CLI-команда `telegram-send-report`;
- полный Markdown-отчёт нужно отправлять как Telegram document/attachment, потому что путь внутри Railway-контейнера не является полезной ссылкой для пользователя;
- короткое summary и diff можно отправлять обычным Telegram message.

### В четверг

Отправка:
- только если найден ближайший weekend event;
- заголовок турнира;
- короткое summary;
- полный Markdown-отчёт как `.md` document/attachment.

### В пятницу и субботу

Отправка:
- только если active monitoring window открыта в четверг;
- заголовок `Что изменилось`;
- короткий список diff-пунктов;
- опционально обновлённый полный отчёт, если изменений много.

## Railway-целевая схема

`Railway` не должен содержать отдельную бизнес-логику. Он только запускает тот же pipeline.

Целевые scheduled jobs:

- `Thursday weekend-check + baseline`
- `Friday incremental if active weekend window exists`
- `Saturday incremental if active weekend window exists`

Переменные окружения:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_PARSE_MODE`
- `UFC_REPORT_TIMEZONE`
- `UFC_DATA_DIR`
- `UFC_DEFAULT_EVENT_MODE`
- `ESPN_ENABLED`
- `TAPOLOGY_ENABLED`
- `SHERDOG_ENABLED`

## Этапы проекта

### Этап 1. Manual report inside Codex

Сделать:
- зафиксировать структуру данных;
- написать минимальный ручной workflow;
- научиться собирать один отчёт по ближайшему турниру;
- проверить шаблон отчёта на одном реальном кейсе.

Критерий готовности:
- в `02_fight-analysis` появляется качественный отчёт, который реально помогает готовить ставки.

### Этап 2. Local scriptable pipeline

Сделать:
- вынести сбор в Python-модули;
- добавить source adapters;
- нормализовать данные;
- сохранять snapshots.

Критерий готовности:
- один CLI-запуск создаёт повторяемый отчёт без ручного копипаста.

### Этап 3. Diff monitoring

Сделать:
- event eligibility check для ближайших выходных;
- content hashing;
- сравнение snapshots;
- meaningful change detection;
- state store, включая active weekend window.

Критерий готовности:
- если weekend event отсутствует, система в эту неделю ничего не шлёт;
- если weekend event есть, пятница и суббота не шлют дубли, а шлют только реальные изменения.

### Этап 4. Telegram delivery

Сделать:
- формат baseline message;
- формат diff update;
- отправку Markdown-отчёта как Telegram document;
- safe handling длинных отчётов.

Критерий готовности:
- baseline и updates доходят в Telegram в удобочитаемом виде.

### Этап 5. Railway deployment

Сделать:
- отдельный service или соседний module рядом с текущим bot stack;
- env configuration;
- scheduler;
- runtime storage;
- журналы ошибок.

Критерий готовности:
- pipeline работает при выключенном локальном компьютере.

## Рекомендуемый следующий шаг

Сейчас имеет смысл делать `Этап 2`.

Практически это значит:

1. Поднять direct-source adapters, начиная с `ESPN`.
2. Научиться собирать event card и fighter history без ручного Markdown-источника.
3. Сохранять runtime snapshot и Markdown, собранные напрямую из источника.
4. После этого добавлять news-layer, fallback-источники и diff logic.
5. Только после этого переносить логику в полноценные скрипты.
