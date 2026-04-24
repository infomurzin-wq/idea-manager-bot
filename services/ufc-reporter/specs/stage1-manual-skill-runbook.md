# Stage 1 Manual Skill Runbook

## Skill

- Skill name: `ufc-weekly-report-prep`
- Skill path: `/Users/amur/.codex/skills/ufc-weekly-report-prep`

## Purpose

Stage 1 exists to prove that the research workflow and report format are useful before any real automation work starts.

The output is manual, but repeatable.

## What Stage 1 Must Do

- identify the target UFC event;
- gather card and fighter data from agreed sources;
- produce a Markdown report inside the project;
- make missing data and source quality explicit.

## Recommended Prompts

- `Use $ufc-weekly-report-prep to prepare a report for the next UFC event.`
- `Use $ufc-weekly-report-prep to prepare a report for UFC <event>.`
- `Используй $ufc-weekly-report-prep и подготовь детальный отчёт по ближайшему UFC-турниру на русском.`

## Shortest Reliable Prompt

Самый короткий и надёжный вариант для будущих сессий:

- `Используй $ufc-weekly-report-prep и подготовь полный детальный отчёт по ближайшему UFC-турниру на русском.`

Без `$ufc-weekly-report-prep` это тоже иногда может сработать по смыслу, но явное имя skill-а надёжнее.

## Output Location

- `/Users/amur/Documents/MYCODEX/ufc-betting/02_fight-analysis/`

## Smoke-Test Artifact

Current pilot report:

- [2026-04-25-ufc-fight-night-sterling-vs-zalal-phase1-pilot.md](/Users/amur/Documents/MYCODEX/ufc-betting/02_fight-analysis/2026-04-25-ufc-fight-night-sterling-vs-zalal-phase1-pilot.md)

## Exit Criteria For Stage 1

Stage 1 is good enough when:

- the skill can be invoked by name in a fresh session;
- a report can be saved to the project without inventing structure ad hoc;
- the report includes last-five history and method summaries at least for a real event sample;
- the report includes a meaningful pre-fight signal check for each fighter;
- the output is useful for actual betting preparation.

## What Comes Next

After Stage 1 is accepted:

- create local Python modules and CLI commands;
- add state, snapshots, and diff logic;
- only then move to Telegram and `Railway`.
