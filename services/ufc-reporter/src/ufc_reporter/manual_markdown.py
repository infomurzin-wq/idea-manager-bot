from __future__ import annotations

import re
from pathlib import Path

from .models import (
    BoutSnapshot,
    EventSnapshot,
    FighterSnapshot,
    FightResultEntry,
    PreFightSignal,
    ReportSnapshot,
)
from .normalize import compute_content_hash, report_payload_for_hash, slugify, strip_backticks, utc_timestamp


def _section(text: str, start: str, end: str | None = None) -> str:
    start_idx = text.index(start) + len(start)
    end_idx = text.index(end, start_idx) if end else len(text)
    return text[start_idx:end_idx].strip()


def _parse_nested_sources(lines: list[str], start_index: int) -> tuple[list[str], int]:
    items: list[str] = []
    index = start_index
    while index < len(lines):
        line = lines[index]
        if line.startswith("  - "):
            items.append(line[4:].strip())
            index += 1
            continue
        break
    return items, index


def _parse_keyed_bullets(block: str) -> dict[str, str | list[str]]:
    lines = [line.rstrip() for line in block.splitlines() if line.strip()]
    payload: dict[str, str | list[str]] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^- .+:$", line):
            key = strip_backticks(line[2:-1].strip())
            sources, next_index = _parse_nested_sources(lines, index + 1)
            payload[key] = sources
            index = next_index
            continue
        match = re.match(r"^- ([^:]+): (.+)$", line)
        if match:
            payload[strip_backticks(match.group(1).strip())] = strip_backticks(
                match.group(2).strip()
            )
        index += 1
    return payload


def _parse_table_rows(table_block: str) -> list[FightResultEntry]:
    rows: list[FightResultEntry] = []
    for line in table_block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if stripped.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells[:2] == ["Дата", "Соперник"]:
            continue
        if len(cells) != 7:
            continue
        rows.append(
            FightResultEntry(
                fight_date=cells[0],
                opponent=cells[1],
                result=cells[2],
                method=cells[3],
                round=cells[4],
                promotion=cells[5],
                event_name=cells[6],
            )
        )
    return rows


def _extract_subblock(block: str, start_label: str, end_label: str | None = None) -> str:
    start_idx = block.index(start_label) + len(start_label)
    end_idx = block.index(end_label, start_idx) if end_label else len(block)
    return block[start_idx:end_idx].strip()


def _parse_signal_block(block: str) -> list[PreFightSignal]:
    bullet_lines = [line[2:].strip() for line in block.splitlines() if line.startswith("- ")]
    if not bullet_lines:
        return []
    source = "n/a"
    summary_parts: list[str] = []
    for item in bullet_lines:
        if item.startswith("Источник:"):
            source = item.split(":", 1)[1].strip()
        else:
            summary_parts.append(item)
    summary = " ".join(summary_parts).strip() or "Существенных предбоевых сигналов не найдено."
    signal_type = "none" if "не найдено" in summary.lower() else "context"
    return [PreFightSignal(summary_ru=summary, source=source, signal_type=signal_type)]


def _parse_fighter_block(block: str, fighter_name: str) -> FighterSnapshot:
    meta_block = _extract_subblock(block, f"#### {fighter_name}", "Последние 5:")
    after_last_five = block.split("Последние 5:", 1)[1]
    lines = after_last_five.lstrip("\n").splitlines()
    table_lines: list[str] = []
    index = 0
    while index < len(lines) and lines[index].startswith("|"):
        table_lines.append(lines[index])
        index += 1
    remainder = "\n".join(lines[index:]).strip()
    comment_block = _extract_subblock(remainder, "Короткий комментарий:", "Предбоевые сигналы:")
    signals_block = remainder.split("Предбоевые сигналы:", 1)[1].strip()

    parsed_meta = _parse_keyed_bullets(meta_block)
    additional_notes = []
    if "Дополнительно" in parsed_meta:
        additional_notes.append(str(parsed_meta["Дополнительно"]))

    return FighterSnapshot(
        fighter_slug=slugify(fighter_name),
        fighter_name=fighter_name,
        record_summary=str(parsed_meta.get("Рекорд", "n/a")),
        wins_summary=str(parsed_meta.get("Победы по методам", "n/a")),
        losses_summary=str(parsed_meta.get("Поражения по методам", "n/a")),
        sources=list(parsed_meta.get("Источники", [])),
        last_five=_parse_table_rows("\n".join(table_lines)),
        fighter_commentary_ru=" ".join(
            line[2:].strip() for line in comment_block.splitlines() if line.startswith("- ")
        ),
        pre_fight_signals=_parse_signal_block(signals_block),
        additional_notes=additional_notes,
        data_quality="good",
    )


def _split_bout_blocks(text: str) -> list[str]:
    parts = re.split(r"(?m)^### ", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _parse_bout_block(block: str) -> BoutSnapshot:
    lines = block.splitlines()
    title = lines[0].strip()
    fighter_a_name, fighter_b_name = [part.strip() for part in title.split(" vs. ", 1)]
    body = "\n".join(lines[1:]).strip()
    metadata_match = re.search(r"^`([^`]+)` \| `([^`]+)` \| `([^`]+)`$", body, re.MULTILINE)
    if not metadata_match:
        raise ValueError(f"Could not parse bout metadata for: {title}")
    weight_class, card_segment, status = metadata_match.groups()
    lines_block = _extract_subblock(body, "#### Линии", f"#### {fighter_a_name}")
    line_values = _parse_keyed_bullets(lines_block)

    fighter_b_marker = f"#### {fighter_b_name}"
    fighter_a_block = _extract_subblock(body, f"#### {fighter_a_name}", fighter_b_marker)
    fighter_b_block = fighter_b_marker + body.split(fighter_b_marker, 1)[1].split(
        "Комментарий по бою:", 1
    )[0]
    bout_commentary_block = body.split("Комментарий по бою:", 1)[1].strip()
    bout_commentary = " ".join(
        line[2:].strip()
        for line in bout_commentary_block.splitlines()
        if line.startswith("- ")
    )

    return BoutSnapshot(
        bout_id=slugify(title),
        fighter_a_name=fighter_a_name,
        fighter_b_name=fighter_b_name,
        weight_class=weight_class,
        card_segment=card_segment,
        status=status,
        fighter_a_moneyline_decimal=str(line_values.get(fighter_a_name, "n/a")),
        fighter_b_moneyline_decimal=str(line_values.get(fighter_b_name, "n/a")),
        over_1_5_decimal=str(line_values.get("ТБ 1.5", "n/a")),
        over_2_5_decimal=str(line_values.get("ТБ 2.5", "n/a")),
        fighter_a=_parse_fighter_block(
            f"#### {fighter_a_name}\n{fighter_a_block}", fighter_a_name
        ),
        fighter_b=_parse_fighter_block(fighter_b_block, fighter_b_name),
        bout_commentary_ru=bout_commentary,
    )


def parse_manual_markdown_report(markdown_text: str, source_path: str = "n/a") -> ReportSnapshot:
    title_line = next(
        line[2:].strip() for line in markdown_text.splitlines() if line.startswith("# ")
    )
    if " — " in title_line:
        event_name, report_title_suffix = title_line.split(" — ", 1)
    else:
        event_name, report_title_suffix = title_line, "Stage 2 Report"

    tournament_section = _section(markdown_text, "## Турнир", "## Качество данных")
    quality_section = _section(markdown_text, "## Качество данных", "## Легенда")
    bouts_section = _section(
        markdown_text,
        "## Бои",
        "## Финальные замечания" if "## Финальные замечания" in markdown_text else None,
    )
    final_notes_section = (
        _section(markdown_text, "## Финальные замечания", None)
        if "## Финальные замечания" in markdown_text
        else ""
    )

    tournament_payload = _parse_keyed_bullets(tournament_section)
    quality_notes = [
        line[2:].strip()
        for line in quality_section.splitlines()
        if line.startswith("- ")
        and not line.startswith("- Формат отчёта:")
        and not line.startswith("- Язык:")
        and not line.startswith("- Odds format:")
    ]

    final_notes = [
        line[2:].strip()
        for line in final_notes_section.splitlines()
        if line.startswith("- ")
    ]

    event_date = str(tournament_payload.get("Дата", "n/a"))
    event_slug = slugify(str(tournament_payload.get("Турнир", event_name)))
    primary_sources = list(tournament_payload.get("Основные источники", []))
    event = EventSnapshot(
        event_id=f"{event_date}-{event_slug}",
        event_name=str(tournament_payload.get("Турнир", event_name)),
        event_date=event_date,
        event_slug=event_slug,
        event_url=primary_sources[0] if primary_sources else "n/a",
        source="manual_markdown_import",
        venue=str(tournament_payload.get("Арена", "n/a")),
        promotion=str(tournament_payload.get("Промоушен", "n/a")),
        broadcast=str(tournament_payload.get("Формат трансляции", "n/a")),
        confirmed_bouts=str(tournament_payload.get("Подтверждённых боёв", "n/a")),
        primary_sources=primary_sources,
        report_title_suffix=report_title_suffix,
        report_format=str(_parse_keyed_bullets(quality_section).get("Формат отчёта", "full-card detailed")),
        language=str(_parse_keyed_bullets(quality_section).get("Язык", "русский")),
        odds_format=str(_parse_keyed_bullets(quality_section).get("Odds format", "decimal only")),
        quality_label=_extract_quality_label(quality_notes),
        quality_notes=quality_notes,
        final_notes=final_notes,
        bouts=[_parse_bout_block(block) for block in _split_bout_blocks(bouts_section)],
    )
    report = ReportSnapshot(
        event=event,
        generated_at=utc_timestamp(),
        report_version=report_title_suffix,
        content_hash="pending",
        source_report_path=source_path,
    )
    payload = report.to_dict()
    report.content_hash = compute_content_hash(report_payload_for_hash(payload))
    return report


def _extract_quality_label(quality_notes: list[str]) -> str:
    for note in quality_notes:
        match = re.search(r"`(good|partial|weak)`", note)
        if match:
            return match.group(1)
    return "partial"


def parse_manual_markdown_path(path: Path) -> ReportSnapshot:
    return parse_manual_markdown_report(
        path.read_text(encoding="utf-8"),
        source_path=str(path),
    )
