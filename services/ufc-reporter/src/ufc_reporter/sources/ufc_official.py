from __future__ import annotations

from lxml import html as lxml_html

from ..models import BoutSnapshot, EventSnapshot, FighterSnapshot
from ..normalize import fighter_name_score, last_name, slugify
from .http import fetch_text

UFC_EVENTS_INDEX_URL = "https://www.ufc.com/events"


def enrich_event_with_fallback_card(event: EventSnapshot) -> EventSnapshot:
    event_url = discover_event_url(event)
    if not event_url:
        event.quality_notes.append(
            "Fallback card: официальный UFC event URL автоматически не найден, поэтому запасная карточка не использовалась."
        )
        return event

    page_html = fetch_text(event_url, cache_namespace="ufc_official")
    fallback_bouts = parse_event_card(page_html)
    if not fallback_bouts:
        event.quality_notes.append(
            "Fallback card: UFC.com event page найдена, но карточка из неё не распарсилась."
        )
        return event

    matched = 0
    added = 0
    existing = list(event.bouts)
    merged: list[BoutSnapshot] = []
    used_existing: set[int] = set()

    for fallback in fallback_bouts:
        match_index = _find_existing_bout_index(fallback, existing, used_existing)
        if match_index is None:
            merged.append(_build_placeholder_bout(fallback, event_url))
            added += 1
            continue
        used_existing.add(match_index)
        matched += 1
        bout = existing[match_index]
        if bout.weight_class == "n/a":
            bout.weight_class = fallback.weight_class
        if bout.card_segment == "n/a":
            bout.card_segment = fallback.card_segment
        merged.append(bout)

    for index, bout in enumerate(existing):
        if index not in used_existing:
            merged.append(bout)

    event.bouts = merged
    event.confirmed_bouts = str(len(event.bouts))
    source_link = f"[UFC.com event page]({event_url})"
    if source_link not in event.primary_sources:
        event.primary_sources.append(source_link)
    if "ufc_official_fallback" not in event.source:
        event.source = f"{event.source} + ufc_official_fallback"
    event.quality_notes.append(
        f"Fallback card: UFC.com подтвердил {len(fallback_bouts)} боёв; сматчено {matched}, добавлено missing bouts: {added}."
    )
    if added:
        event.final_notes.append(
            "Часть боёв была добавлена из UFC.com fallback card, потому что ESPN event payload в текущем прогоне был неполным."
        )
    return event


def discover_event_url(event: EventSnapshot) -> str | None:
    index_html = fetch_text(UFC_EVENTS_INDEX_URL, cache_namespace="ufc_official")
    candidates: list[tuple[int, str]] = []
    if not event.bouts:
        return None
    main_fight = event.bouts[0]
    a_last = last_name(main_fight.fighter_a_name)
    b_last = last_name(main_fight.fighter_b_name)
    for match in lxml_html.fromstring(index_html).xpath("//a[starts-with(@href, '/event/')]"):
        href = match.get("href", "").strip()
        if not href:
            continue
        snippet = " ".join(match.itertext())
        window = snippet.lower()
        score = 0
        if a_last in slugify(window):
            score += 5
        if b_last in slugify(window):
            score += 5
        if event.event_date.split("-")[2] in href:
            score += 1
        if event.event_date.split("-")[0] in href:
            score += 1
        if score:
            candidates.append((score, href))
    if not candidates:
        raw = index_html.lower()
        for href in set(lxml_html.fromstring(index_html).xpath("//a[starts-with(@href, '/event/')]/@href")):
            snippet_index = raw.find(href.lower())
            if snippet_index == -1:
                continue
            window = raw[max(0, snippet_index - 5000) : snippet_index + 5000]
            score = 0
            if a_last in slugify(window):
                score += 5
            if b_last in slugify(window):
                score += 5
            if event.event_date.replace("-", "")[:6] in window.replace("-", ""):
                score += 1
            if score:
                candidates.append((score, href))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return f"https://www.ufc.com{candidates[0][1]}"


def parse_event_card(page_html: str) -> list[BoutSnapshot]:
    document = lxml_html.fromstring(page_html)
    ticker_red = [node.text_content().strip() for node in document.xpath("//div[contains(@class, 'c-listing-ticker-fightcard__red_corner_name')]")]
    ticker_blue = [node.text_content().strip() for node in document.xpath("//div[contains(@class, 'c-listing-ticker-fightcard__blue_corner_name')]")]
    fight_nodes = document.xpath("//div[contains(@class, 'c-listing-fight') and @data-fmid]")
    headings = [
        (node.sourceline or 0, node.text_content().strip())
        for node in document.xpath("//h3")
        if node.text_content().strip() in {"Main Card", "Prelims", "Early Prelims"}
    ]
    fight_meta: list[dict[str, str]] = []
    for node in fight_nodes:
        fight_meta.append(
            {
                "bout_id": str(node.get("data-fmid", slugify(f"ufc-official-{len(fight_meta)}"))),
                "card_segment": _segment_for_line(node.sourceline or 0, headings),
                "weight_class": _translate_weight_class(
                    " ".join(
                        part.strip()
                        for part in node.xpath(".//div[contains(@class, 'c-listing-fight__class-text')][1]//text()")
                        if part.strip()
                    )
                ),
            }
        )
    if not ticker_red or len(ticker_red) != len(ticker_blue) or len(ticker_red) != len(fight_meta):
        return []

    aligned: list[BoutSnapshot] = []
    for red_name, blue_name, meta in zip(ticker_red, ticker_blue, reversed(fight_meta)):
        aligned.append(
            BoutSnapshot(
                bout_id=meta["bout_id"],
                fighter_a_name=red_name,
                fighter_b_name=blue_name,
                weight_class=meta["weight_class"],
                card_segment=meta["card_segment"],
                status="n/a",
                bout_commentary_ru="Бой присутствует в официальной карточке UFC, но полный direct-source разбор по ESPN в этом прогоне недоступен.",
            )
        )
    return list(reversed(aligned))


def _segment_for_line(line: int, headings: list[tuple[int, str]]) -> str:
    current = "Card"
    for heading_line, label in headings:
        if heading_line <= line:
            current = label
    mapping = {
        "Main Card": "Main Card",
        "Prelims": "Prelim",
        "Early Prelims": "Early Prelim",
    }
    return mapping.get(current, current)


def _translate_weight_class(raw_value: str) -> str:
    value = _dedupe_repeated_phrase(raw_value.strip().strip("-").strip())
    if value.endswith(" Bout"):
        value = value[: -len(" Bout")].strip()
    mapping = {
        "Полулегкий вес": "Featherweight",
        "Легчайший вес": "Bantamweight",
        "Наилегчайший вес": "Flyweight",
        "Легкий вес": "Lightweight",
        "Полусредний вес": "Welterweight",
        "Средний вес": "Middleweight",
        "Полутяжелый вес": "Light Heavyweight",
        "Тяжелый вес": "Heavyweight",
        "Женский минимальный вес": "Women's Strawweight",
        "Женский наилегчайший вес": "Women's Flyweight",
        "Женский легчайший вес": "Women's Bantamweight",
    }
    return mapping.get(value, value or "n/a")


def _dedupe_repeated_phrase(value: str) -> str:
    words = value.split()
    if len(words) >= 2 and len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            return " ".join(words[:half])
    return value


def _find_existing_bout_index(
    fallback: BoutSnapshot,
    existing: list[BoutSnapshot],
    used_existing: set[int],
) -> int | None:
    best: tuple[int, int] | None = None
    for index, bout in enumerate(existing):
        if index in used_existing:
            continue
        direct = fighter_name_score(fallback.fighter_a_name, bout.fighter_a_name) + fighter_name_score(
            fallback.fighter_b_name, bout.fighter_b_name
        )
        reverse = fighter_name_score(fallback.fighter_a_name, bout.fighter_b_name) + fighter_name_score(
            fallback.fighter_b_name, bout.fighter_a_name
        )
        score = max(direct, reverse)
        if score < 8:
            continue
        if not best or score > best[0]:
            best = (score, index)
    return best[1] if best else None


def _build_placeholder_fighter(name: str, source_url: str) -> FighterSnapshot:
    return FighterSnapshot(
        fighter_slug=slugify(name),
        fighter_name=name,
        record_summary="n/a",
        wins_summary="n/a",
        losses_summary="n/a",
        sources=[f"[UFC.com event page]({source_url})"],
        fighter_commentary_ru="Профиль бойца пока заполнен только через fallback card source: ESPN direct-source в этом прогоне не отдал его history block.",
        data_quality="fallback_only",
        additional_notes=[
            "Боец добавлен через UFC.com fallback card; последние 5 боёв и summary stats пока недоступны в текущем прогоне."
        ],
    )


def _build_placeholder_bout(fallback: BoutSnapshot, source_url: str) -> BoutSnapshot:
    return BoutSnapshot(
        bout_id=fallback.bout_id,
        fighter_a_name=fallback.fighter_a_name,
        fighter_b_name=fallback.fighter_b_name,
        weight_class=fallback.weight_class,
        card_segment=fallback.card_segment,
        status="n/a",
        fighter_a=fallback.fighter_a or _build_placeholder_fighter(fallback.fighter_a_name, source_url),
        fighter_b=fallback.fighter_b or _build_placeholder_fighter(fallback.fighter_b_name, source_url),
        bout_commentary_ru="Бой подтянут из официальной карточки UFC как fallback, потому что ESPN event payload в текущем прогоне был неполным.",
    )
