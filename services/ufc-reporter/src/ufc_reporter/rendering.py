from __future__ import annotations

from .models import BoutSnapshot, FighterSnapshot, ReportSnapshot


def _render_bullets(items: list[str], indent: str = "- ") -> list[str]:
    return [f"{indent}{item}" for item in items]


def _render_last_five_table(fighter: FighterSnapshot) -> list[str]:
    lines = [
        "| Дата | Соперник | Результат | Метод | Раунд | Промоушен | Ивент |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not fighter.last_five:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
        return lines
    for fight in fighter.last_five:
        lines.append(
            "| "
            + " | ".join(
                [
                    fight.fight_date,
                    fight.opponent,
                    fight.result,
                    fight.method,
                    fight.round,
                    fight.promotion,
                    fight.event_name,
                ]
            )
            + " |"
        )
    return lines


def _render_fighter(fighter: FighterSnapshot) -> list[str]:
    lines = [
        f"#### {fighter.fighter_name}",
        "",
        f"- Рекорд: `{fighter.record_summary}`",
        f"- Победы по методам: `{fighter.wins_summary}`",
        f"- Поражения по методам: `{fighter.losses_summary}`",
    ]
    for note in fighter.additional_notes:
        lines.append(f"- Дополнительно: `{note}`")
    lines.append("- Источники:")
    lines.extend(_render_bullets(fighter.sources, indent="  - "))
    lines.extend(
        [
            "",
            "Последние 5:",
            "",
            *_render_last_five_table(fighter),
            "",
            "Короткий комментарий:",
            "",
            f"- {fighter.fighter_commentary_ru}",
            "",
            "Предбоевые сигналы:",
            "",
        ]
    )
    if fighter.pre_fight_signals:
        for signal in fighter.pre_fight_signals:
            lines.append(f"- {signal.summary_ru}")
            lines.append(f"- Источник: {signal.source}")
    else:
        lines.append("- Существенных предбоевых сигналов не найдено.")
        lines.append("- Источник: `n/a`")
    return lines


def _render_bout(bout: BoutSnapshot) -> list[str]:
    lines = [
        f"### {bout.fighter_a_name} vs. {bout.fighter_b_name}",
        "",
        f"`{bout.weight_class}` | `{bout.card_segment}` | `{bout.status}`",
        "",
        "#### Линии",
        "",
        f"- `{bout.fighter_a_name}`: `{bout.fighter_a_moneyline_decimal}`",
        f"- `{bout.fighter_b_name}`: `{bout.fighter_b_moneyline_decimal}`",
        f"- `ТБ 1.5`: `{bout.over_1_5_decimal}`",
        f"- `ТБ 2.5`: `{bout.over_2_5_decimal}`",
        "",
    ]
    if bout.fighter_a:
        lines.extend(_render_fighter(bout.fighter_a))
        lines.append("")
    if bout.fighter_b:
        lines.extend(_render_fighter(bout.fighter_b))
        lines.append("")
    lines.extend(
        [
            "Комментарий по бою:",
            "",
            f"- {bout.bout_commentary_ru}",
        ]
    )
    return lines


def render_report(report: ReportSnapshot) -> str:
    event = report.event
    lines = [
        f"# {event.event_name} — {event.report_title_suffix}",
        "",
        "## Турнир",
        "",
        f"- Турнир: `{event.event_name}`",
        f"- Дата: `{event.event_date}`",
        f"- Арена: `{event.venue}`",
        f"- Промоушен: `{event.promotion}`",
        f"- Формат трансляции: `{event.broadcast}`",
        f"- Подтверждённых боёв: `{event.confirmed_bouts}`",
        "- Основные источники:",
        *_render_bullets(event.primary_sources, indent="  - "),
        "",
        "## Качество данных",
        "",
        f"- Формат отчёта: `{event.report_format}`",
        f"- Язык: `{event.language}`",
        f"- Odds format: `{event.odds_format}`",
        *_render_bullets(event.quality_notes),
        "",
        "## Легенда",
        "",
        "- `🟩 W` — победа",
        "- `🟥 L` — поражение",
        "- `🟨 D` — ничья",
        "- `⬜ NC` — no contest",
        "",
        "## Бои",
        "",
    ]
    for index, bout in enumerate(event.bouts):
        lines.extend(_render_bout(bout))
        if index != len(event.bouts) - 1:
            lines.extend(["", "---", ""])
    if event.final_notes:
        lines.extend(["", "## Финальные замечания", ""])
        lines.extend(_render_bullets(event.final_notes))
    return "\n".join(lines).rstrip() + "\n"
