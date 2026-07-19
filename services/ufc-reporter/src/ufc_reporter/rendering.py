from __future__ import annotations

from datetime import date

from .models import BoutSnapshot, FighterSnapshot, ReportSnapshot


def _render_bullets(items: list[str], indent: str = "- ") -> list[str]:
    return [f"{indent}{item}" for item in items]


def _render_last_five_entries(fighter: FighterSnapshot) -> list[str]:
    if not fighter.last_five:
        return ["- `n/a`"]
    lines: list[str] = []
    for fight in fighter.last_five:
        lines.append(
            (
                f"- `{_format_fight_date(fight.fight_date)}` | {fight.opponent} | "
                f"{fight.result} | {fight.method} | {_format_round(fight.round)} | "
                f"{fight.promotion} | {fight.event_name}"
            )
        )
    return lines


def _format_fight_date(raw_value: str) -> str:
    try:
        parsed = date.fromisoformat(raw_value)
    except ValueError:
        return raw_value
    return parsed.strftime("%d.%m.%Y")


def _format_round(raw_value: str) -> str:
    if raw_value == "n/a":
        return raw_value
    return f"R{raw_value}"


def _meaningful_pre_fight_signals(fighter: FighterSnapshot) -> list[str]:
    empty_signal_text = "существенных предбоевых сигналов не найдено"
    return [
        signal.summary_ru
        for signal in fighter.pre_fight_signals
        if signal.signal_type != "none"
        and empty_signal_text not in signal.summary_ru.lower()
    ]


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
    lines.extend(
        [
            "",
            "Последние 5:",
            "",
            *_render_last_five_entries(fighter),
        ]
    )
    meaningful_signals = _meaningful_pre_fight_signals(fighter)
    if meaningful_signals:
        lines.extend(["", "Предбоевые сигналы:", ""])
        for signal in meaningful_signals:
            lines.append(f"- {signal}")
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
    if bout.odds_source_note:
        lines.extend(
            [
                f"- Источник альтернативной линии: `{bout.odds_source_note}`",
                "",
            ]
        )
    if bout.fighter_a:
        lines.extend(_render_fighter(bout.fighter_a))
        lines.append("")
    if bout.fighter_b:
        lines.extend(_render_fighter(bout.fighter_b))
        lines.append("")
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
    return "\n".join(lines).rstrip() + "\n"
