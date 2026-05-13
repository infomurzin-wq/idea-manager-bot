from __future__ import annotations

from .models import BoutSnapshot, FighterSnapshot, PreFightSignal, ReportSnapshot


def render_incremental_diff(previous: ReportSnapshot | None, current: ReportSnapshot) -> str:
    if previous is None:
        return _render_without_previous(current)

    lines = [
        f"# Обновления: {current.event.event_name}",
        "",
        "## Сводка",
        "",
        f"- Дата турнира: `{current.event.event_date}`",
        "- Ниже только изменения относительно последней отправленной версии.",
        "",
    ]
    changes = _event_changes(previous, current)
    if not changes:
        changes.append("Meaningful hash изменился, но человекочитаемых отличий в отслеживаемых полях не найдено.")
    lines.extend(_bullets(changes))
    lines.append("")

    previous_bouts = {_bout_key(bout): bout for bout in previous.event.bouts}
    current_bouts = {_bout_key(bout): bout for bout in current.event.bouts}

    added_keys = [key for key in current_bouts if key not in previous_bouts]
    removed_keys = [key for key in previous_bouts if key not in current_bouts]
    changed_sections: list[tuple[str, list[str]]] = []

    for key in added_keys:
        bout = current_bouts[key]
        changed_sections.append(
            (
                f"{bout.fighter_a_name} vs. {bout.fighter_b_name}",
                [f"Добавлен бой: `{bout.weight_class}` | `{bout.card_segment}` | `{bout.status}`"],
            )
        )
    for key in removed_keys:
        bout = previous_bouts[key]
        changed_sections.append(
            (
                f"{bout.fighter_a_name} vs. {bout.fighter_b_name}",
                ["Бой исчез из текущей версии карда."],
            )
        )
    for key in current_bouts:
        if key not in previous_bouts:
            continue
        bout_changes = _bout_changes(previous_bouts[key], current_bouts[key])
        if bout_changes:
            bout = current_bouts[key]
            changed_sections.append((f"{bout.fighter_a_name} vs. {bout.fighter_b_name}", bout_changes))

    if changed_sections:
        lines.extend(["## Изменения по боям", ""])
        for title, items in changed_sections:
            lines.extend([f"### {title}", ""])
            lines.extend(_bullets(items))
            lines.append("")
    else:
        lines.extend(["## Изменения по боям", "", "- Изменений по боям в отслеживаемых полях не найдено.", ""])

    return "\n".join(lines).rstrip() + "\n"


def _render_without_previous(current: ReportSnapshot) -> str:
    return "\n".join(
        [
            f"# Обновления: {current.event.event_name}",
            "",
            "Не найден сохранённый previous snapshot для сравнения.",
            "Текущая версия сохранена как новая база для следующих incremental-запусков.",
            "",
            f"- Дата турнира: `{current.event.event_date}`",
            f"- Боёв в текущем отчёте: `{current.event.confirmed_bouts}`",
        ]
    ) + "\n"


def _event_changes(previous: ReportSnapshot, current: ReportSnapshot) -> list[str]:
    changes: list[str] = []
    _append_change(changes, "Название турнира", previous.event.event_name, current.event.event_name)
    _append_change(changes, "Дата турнира", previous.event.event_date, current.event.event_date)
    _append_change(changes, "Арена", previous.event.venue, current.event.venue)
    _append_change(changes, "Подтверждённых боёв", previous.event.confirmed_bouts, current.event.confirmed_bouts)
    for note in _new_items(previous.event.quality_notes, current.event.quality_notes):
        changes.append(f"Новое замечание по качеству данных: {note}")
    for note in _new_items(previous.event.final_notes, current.event.final_notes):
        changes.append(f"Новое финальное замечание: {note}")
    return changes


def _bout_changes(previous: BoutSnapshot, current: BoutSnapshot) -> list[str]:
    changes: list[str] = []
    _append_change(changes, "Весовая категория", previous.weight_class, current.weight_class)
    _append_change(changes, "Сегмент карда", previous.card_segment, current.card_segment)
    _append_change(changes, "Статус боя", previous.status, current.status)
    _append_change(
        changes,
        f"Коэффициент {current.fighter_a_name}",
        previous.fighter_a_moneyline_decimal,
        current.fighter_a_moneyline_decimal,
    )
    _append_change(
        changes,
        f"Коэффициент {current.fighter_b_name}",
        previous.fighter_b_moneyline_decimal,
        current.fighter_b_moneyline_decimal,
    )
    _append_change(changes, "ТБ 1.5", previous.over_1_5_decimal, current.over_1_5_decimal)
    _append_change(changes, "ТБ 2.5", previous.over_2_5_decimal, current.over_2_5_decimal)
    _append_change(changes, "Комментарий по бою", previous.bout_commentary_ru, current.bout_commentary_ru)

    changes.extend(_fighter_changes(previous.fighter_a, current.fighter_a))
    changes.extend(_fighter_changes(previous.fighter_b, current.fighter_b))
    return changes


def _fighter_changes(previous: FighterSnapshot | None, current: FighterSnapshot | None) -> list[str]:
    if current is None:
        return []
    if previous is None:
        return [f"Добавлен блок бойца `{current.fighter_name}`."]

    changes: list[str] = []
    prefix = current.fighter_name
    _append_change(changes, f"{prefix}: рекорд", previous.record_summary, current.record_summary)
    _append_change(changes, f"{prefix}: победы по методам", previous.wins_summary, current.wins_summary)
    _append_change(changes, f"{prefix}: поражения по методам", previous.losses_summary, current.losses_summary)
    _append_change(changes, f"{prefix}: комментарий", previous.fighter_commentary_ru, current.fighter_commentary_ru)
    _append_change(changes, f"{prefix}: качество данных", previous.data_quality, current.data_quality)

    for note in _new_items(previous.additional_notes, current.additional_notes):
        changes.append(f"{prefix}: новая заметка: {note}")
    for signal in _new_signals(previous.pre_fight_signals, current.pre_fight_signals):
        source = f" Источник: {signal.source}" if signal.source != "n/a" else ""
        impact = f" Влияние: {signal.impact_note_ru}" if signal.impact_note_ru else ""
        changes.append(f"{prefix}: новый предбоевой сигнал: {signal.summary_ru}{impact}{source}")
    return changes


def _append_change(changes: list[str], label: str, old: str, new: str) -> None:
    if _clean(old) == _clean(new):
        return
    changes.append(f"{label}: `{_clean(old)}` -> `{_clean(new)}`")


def _new_items(previous: list[str], current: list[str]) -> list[str]:
    previous_seen = {_clean(item) for item in previous}
    return [item for item in current if _clean(item) not in previous_seen]


def _new_signals(previous: list[PreFightSignal], current: list[PreFightSignal]) -> list[PreFightSignal]:
    previous_seen = {_signal_key(item) for item in previous}
    return [item for item in current if _signal_key(item) not in previous_seen]


def _signal_key(signal: PreFightSignal) -> tuple[str, str, str]:
    return (_clean(signal.summary_ru), _clean(signal.source), _clean(signal.signal_type))


def _bout_key(bout: BoutSnapshot) -> str:
    if bout.bout_id and bout.bout_id != "n/a":
        return bout.bout_id
    names = sorted([bout.fighter_a_name, bout.fighter_b_name])
    return " vs ".join(_clean(name).lower() for name in names)


def _clean(value: str) -> str:
    return str(value or "n/a").strip()


def _bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]
