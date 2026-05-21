#!/usr/bin/env python3
"""Offline prototype: Telegram-like post text -> bond candidate JSONL."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


BOND_KEYWORDS = (
    "облигац",
    "выпуск",
    "размещен",
    "размещение",
    "сбор книги",
    "сбор заявок",
    "книга заявок",
    "купон",
    "ytm",
    "isin",
    "оферт",
    "амортиз",
)

CRITICAL_FIELDS = (
    "issuer",
    "coupon",
    "ytm",
    "book_building_date",
    "placement_date",
    "maturity_date",
    "offer",
    "amortization",
    "coupon_frequency_per_year",
    "coupon_type",
    "rating",
)

MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

CYRILLIC_TO_LATIN = str.maketrans(
    {
        "А": "A",
        "Б": "B",
        "В": "B",
        "Е": "E",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "Х": "X",
        "а": "A",
        "б": "B",
        "в": "B",
        "е": "E",
        "к": "K",
        "м": "M",
        "н": "H",
        "о": "O",
        "р": "P",
        "с": "C",
        "т": "T",
        "х": "X",
    }
)


@dataclass
class SourcePost:
    post_id: str | None
    channel: str | None
    url: str | None
    post_date: str | None
    text: str


@dataclass
class CandidateBlock:
    block_index: int
    text: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract bond candidate cards from JSONL posts.")
    parser.add_argument("input", type=Path, help="Path to JSONL file with Telegram-like posts.")
    args = parser.parse_args()

    for post in read_posts(args.input):
        for card in extract_candidates(post):
            print(json.dumps(card, ensure_ascii=False, sort_keys=True))


def read_posts(path: Path) -> list[SourcePost]:
    posts: list[SourcePost] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            text = str(item.get("text") or "").strip()
            if not text:
                raise ValueError(f"Missing text at {path}:{line_number}")
            posts.append(
                SourcePost(
                    post_id=nullable_str(item.get("id")),
                    channel=nullable_str(item.get("source_channel")),
                    url=nullable_str(item.get("source_url")),
                    post_date=nullable_str(item.get("source_post_date")),
                    text=text,
                )
            )
    return posts


def extract_candidate(post: SourcePost) -> dict[str, Any] | None:
    """Compatibility wrapper for older one-card callers."""
    candidates = extract_candidates(post)
    return candidates[0] if candidates else None


def extract_candidates(post: SourcePost) -> list[dict[str, Any]]:
    text = normalize_text(post.text)
    lowered = text.lower()
    if not looks_relevant(lowered):
        return []
    if is_source_page(post, lowered):
        return []

    default_year = infer_year(post.post_date)
    blocks = split_candidate_blocks(post.text)
    cards: list[dict[str, Any]] = []
    for block in blocks:
        block_text = block.text.strip()
        if not looks_like_candidate_block(block_text):
            continue
        cards.append(build_card(post, block, block_text, default_year))
    return cards


def build_card(post: SourcePost, block: CandidateBlock, text: str, default_year: int) -> dict[str, Any]:
    lowered = text.lower()
    issuer = extract_issuer(text)
    coupon_type = extract_coupon_type(lowered, text)
    coupon_frequency = extract_coupon_frequency(lowered)
    offer = extract_offer(text)
    amortization = extract_amortization(text)
    coupon_terms = extract_coupon_terms(text)
    ytm_terms = extract_ytm_terms(text)

    instrument = {
        "issuer": issuer,
        "issue_name": extract_issue_name(text, issuer),
        "isin": extract_isin(text),
        "rating": extract_rating(text),
    }
    terms = {
        **coupon_terms,
        **ytm_terms,
        "price": extract_price(text),
        "book_building_date": extract_date_after(
            text,
            r"сбор(?:а)? книги|книга заявок|сбор заявок",
            default_year,
        ),
        "placement_date": extract_date_after(
            text,
            r"размещени[ея]|старт размещения|дата размещения",
            default_year,
        ),
        "first_trading_date": extract_date_after(
            text,
            r"перв(?:ый|ого) день торгов|начал[оа] торгов|торги",
            default_year,
        ),
        "maturity_date": extract_date_after(text, r"погашени[ея]|срок", default_year),
        "offer": offer,
        "amortization": amortization,
        "coupon_frequency_per_year": coupon_frequency,
        "coupon_type": coupon_type,
        "issue_size": extract_issue_size(text),
        "qualified_only": extract_qualified_only(lowered),
    }

    missing_fields = sorted(find_missing_fields(instrument, terms))
    red_flags = collect_red_flags(instrument, terms, lowered)
    signal_type = classify_signal_type(text, lowered, terms)
    status = classify_status(missing_fields, red_flags, terms)
    reason = build_reason(status, red_flags, terms, signal_type)

    return {
        "source": {
            "post_id": post.post_id,
            "channel": post.channel,
            "url": post.url,
            "post_date": post.post_date,
            "block_index": block.block_index,
        },
        "signal_type": signal_type,
        "instrument": instrument,
        "terms": terms,
        "assessment": {
            "status": status,
            "interest_reason": reason,
            "red_flags": red_flags,
            "missing_fields": missing_fields,
        },
        "raw_text": normalize_text(post.text),
        "raw_block_text": normalize_text(text),
    }


def split_candidate_blocks(text: str) -> list[CandidateBlock]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    normalized_full = normalize_text(text)

    if re.search(r"эмитент\s*:", text, re.IGNORECASE) and "параметры выпуска" in text.lower():
        return [CandidateBlock(1, text)]

    if count_isin_like(text) > 1:
        blocks = [
            CandidateBlock(index, paragraph)
            for index, paragraph in enumerate(paragraphs, start=1)
            if count_isin_like(paragraph) > 0
        ]
        if blocks:
            return blocks

    blocks: list[CandidateBlock] = []
    used: set[int] = set()
    for index, paragraph in enumerate(paragraphs):
        if index in used:
            continue

        if is_structured_terms_block(paragraph):
            block_parts = []
            previous_index = index - 1
            if (
                previous_index >= 0
                and previous_index not in used
                and is_title_context_paragraph(paragraphs[previous_index])
            ):
                block_parts.append(paragraphs[previous_index])
                used.add(previous_index)
            block_parts.append(paragraph)
            used.add(index)
            for next_index in range(index + 1, min(index + 3, len(paragraphs))):
                next_paragraph = paragraphs[next_index]
                if is_supporting_terms_paragraph(next_paragraph, paragraph):
                    block_parts.append(next_paragraph)
                    used.add(next_index)
                    continue
                if is_structured_terms_block(next_paragraph) or is_parenthetical_candidate(next_paragraph):
                    break
            blocks.append(CandidateBlock(len(blocks) + 1, "\n\n".join(block_parts)))
            continue

        if is_parenthetical_candidate(paragraph):
            used.add(index)
            blocks.append(CandidateBlock(len(blocks) + 1, paragraph))

    if blocks:
        return blocks
    return [CandidateBlock(1, normalized_full)]


def looks_relevant(lowered: str) -> bool:
    matches = sum(1 for keyword in BOND_KEYWORDS if keyword in lowered)
    return matches >= 2


def looks_like_candidate_block(text: str) -> bool:
    lowered = text.lower()
    strong_markers = (
        "isin",
        "ytm",
        "ставка купона",
        "купон:",
        "купон ",
        "флоатер",
        "параметры выпуска",
        "рейтинг:",
        "сбор заявок",
        "дата размещения",
    )
    return any(marker in lowered for marker in strong_markers) and (
        "облигац" in lowered
        or "купон" in lowered
        or "ytm" in lowered
        or "размещ" in lowered
        or "погашени" in lowered
    )


def is_source_page(post: SourcePost, lowered: str) -> bool:
    url = (post.url or "").lower()
    channel = (post.channel or "").lower()
    source_markers = (
        "анализ облигаций",
        "фильтры:",
        "строк в таблице",
        "таблица:",
        "подобрать аналоги",
        "скачать excel",
    )
    if "dohod.ru/analytic/bonds" in url or channel.startswith("web:"):
        return sum(1 for marker in source_markers if marker in lowered) >= 2
    return sum(1 for marker in source_markers if marker in lowered) >= 4


def is_structured_terms_block(paragraph: str) -> bool:
    lowered = paragraph.lower()
    return (
        ("купон:" in lowered or "ставка купона" in lowered or "купонный период" in lowered)
        and ("рейтинг" in lowered or re.search(r"\b(?:ru)?[ABCDАВЕКМНОРСТХ]{1,3}[+-]?", normalize_for_codes(paragraph)))
    )


def is_title_context_paragraph(paragraph: str) -> bool:
    cleaned = normalize_text(paragraph)
    if not cleaned or len(cleaned) > 140:
        return False
    lowered = cleaned.lower()
    if any(marker in lowered for marker in ("купон", "доходность", "ytm", "текущая цена", "дата погашения")):
        return False
    return bool(extract_isin(cleaned) or re.search(r"\b\d{3}[РP]-\d+\b", normalize_for_codes(cleaned), re.IGNORECASE))


def is_supporting_terms_paragraph(candidate: str, anchor: str) -> bool:
    lowered = candidate.lower()
    anchor_lowered = anchor.lower()
    if re.search(r"размещени[ея]|сбор заявок|сбор книги", lowered) and not is_structured_terms_block(candidate):
        return True
    if "амортизац" in lowered and "амортизац" in anchor_lowered:
        return True
    issuer = extract_issuer(anchor)
    if issuer and issuer.lower() in lowered and ("ytm" in lowered or "ставка купона" in lowered):
        return True
    return False


def is_parenthetical_candidate(paragraph: str) -> bool:
    lowered = paragraph.lower()
    return "(" in paragraph and ")" in paragraph and ("ytm" in lowered or "ставка купона" in lowered or "купон" in lowered)


def count_isin_like(text: str) -> int:
    return len(re.findall(r"\bRU[0-9A-ZА-Я]{10}\b", normalize_for_codes(text), re.IGNORECASE))


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_codes(text: str) -> str:
    return text.translate(CYRILLIC_TO_LATIN).replace("–", "-").replace("—", "-")


def nullable_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def infer_year(value: str | None) -> int:
    if not value:
        return date.today().year
    match = re.search(r"\b(20\d{2})\b", value)
    return int(match.group(1)) if match else date.today().year


def extract_isin(text: str) -> str | None:
    normalized = normalize_for_codes(text)
    match = re.search(r"\bRU[0-9A-Z]{10}\b", normalized, re.IGNORECASE)
    return match.group(0).upper() if match else None


def extract_rating(text: str) -> str | None:
    label_match = re.search(r"рейтинг\s*:\s*([^\n,;()]+)", text, re.IGNORECASE)
    if label_match:
        rating = find_rating_token(normalize_for_codes(label_match.group(1)))
        if rating:
            return rating
    parenthetical_rating = extract_parenthetical_rating(text)
    if parenthetical_rating:
        return parenthetical_rating
    normalized = normalize_for_codes(text)
    return find_rating_token(normalized, allow_single_letter=False)


def extract_parenthetical_rating(text: str) -> str | None:
    for content in re.findall(r"\(([^()]*)\)", text):
        if is_rating_group(content):
            rating = find_rating_token(normalize_for_codes(content), allow_single_letter=True)
            if rating:
                return rating
    return None


def is_rating_group(value: str) -> bool:
    normalized = normalize_for_codes(value).upper().replace(" ", "")
    rating_part = r"(?:RU)?(?:AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|CCC|CC|C)(?:[.-]?RU|\|RU\|)?"
    return bool(re.fullmatch(rf"{rating_part}(?:/{rating_part})*", normalized))


def find_rating_token(text: str, allow_single_letter: bool = True) -> str | None:
    token_pattern = r"AAA|AA[+-]?|A[+-]?|BBB[+-]?|BB[+-]?|B[+-]?|CCC|CC|C"
    if not allow_single_letter:
        token_pattern = r"AAA|AA[+-]?|A[+-]|BBB[+-]?|BB[+-]?|B[+-]|CCC|CC"
    match = re.search(
        rf"(?<![A-ZА-Яа-я0-9])(?:ru)?(?:{token_pattern})(?:[.-]?ru|\|ru\|)?(?![A-ZА-Яа-я0-9])",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(0).replace("|ru|", "").replace(".ru", ".ru")


def extract_coupon(text: str) -> str | None:
    return extract_coupon_terms(text)["coupon"]


def extract_coupon_terms(text: str) -> dict[str, str | None]:
    floating = re.search(r"(?:купон|ставка купона)[^КCСR\n]{0,80}((?:КС|KC|RUONIA)\s*\+\s*\d{1,2}(?:[,.]\d{1,2})?\s?%)", text, re.IGNORECASE)
    if floating:
        coupon = normalize_formula(floating.group(1))
        return {"coupon": coupon, "coupon_raw": coupon, "coupon_min": None, "coupon_max": None}

    range_match = extract_percent_range_near(text, r"купон|купоны|ставка купона|ориентир купона")
    if range_match:
        low, high = range_match
        return {
            "coupon": normalize_percent(high),
            "coupon_raw": f"{normalize_percent(low).removesuffix('%')}-{normalize_percent(high)}",
            "coupon_min": normalize_percent(low),
            "coupon_max": normalize_percent(high),
        }

    direct = extract_percent_near(text, r"купон|купоны|ставка купона|ориентир купона")
    if direct:
        return {"coupon": direct, "coupon_raw": direct, "coupon_min": direct, "coupon_max": direct}
    match = re.search(r"купон[^0-9]{0,40}(\d{1,2}(?:[,.]\d{1,2})?)\s?%", text, re.IGNORECASE)
    if match:
        coupon = normalize_percent(match.group(1))
        return {"coupon": coupon, "coupon_raw": coupon, "coupon_min": coupon, "coupon_max": coupon}
    return {"coupon": None, "coupon_raw": None, "coupon_min": None, "coupon_max": None}


def extract_ytm(text: str) -> str | None:
    return extract_ytm_terms(text)["ytm"]


def extract_ytm_terms(text: str) -> dict[str, str | None]:
    range_match = extract_percent_range_near(text, r"YTM|доходность YTM|доходность|доходн\.|доход")
    if range_match:
        low, high = range_match
        return {
            "ytm": normalize_percent(high),
            "ytm_raw": f"{normalize_percent(low).removesuffix('%')}-{normalize_percent(high)}",
            "ytm_min": normalize_percent(low),
            "ytm_max": normalize_percent(high),
        }

    direct = extract_percent_near(text, r"YTM|доходность YTM|доходность|доходн\.|доход")
    if direct:
        return {"ytm": direct, "ytm_raw": direct, "ytm_min": direct, "ytm_max": direct}
    return {"ytm": None, "ytm_raw": None, "ytm_min": None, "ytm_max": None}


def extract_percent_near(text: str, label_pattern: str) -> str | None:
    match = re.search(rf"(?:{label_pattern})[^%\n]{{0,100}}?(\d{{1,3}}(?:[,.]\d{{1,2}})?)\s?%", text, re.IGNORECASE)
    if match:
        return normalize_percent(match.group(1))
    return None


def extract_percent_range_near(text: str, label_pattern: str) -> tuple[str, str] | None:
    match = re.search(
        rf"(?:{label_pattern})[^%\n]{{0,100}}?(\d{{1,3}}(?:[,.]\d{{1,2}})?)\s*(?:-|–|—|до)\s*(\d{{1,3}}(?:[,.]\d{{1,2}})?)\s?%",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1), match.group(2)
    return None


def normalize_percent(value: str) -> str:
    return f"{value.replace(',', '.').replace(' ', '')}%"


def normalize_formula(value: str) -> str:
    return value.upper().replace(",", ".").replace(" ", "")


def extract_price(text: str) -> str | None:
    match = re.search(r"(?:цена|по цене|стоимость(?: облигации)?)[^%\n]{0,50}?(\d{2,3}(?:[,.]\d+)?)\s?%", text, re.IGNORECASE)
    return normalize_percent(match.group(1)) if match else None


def extract_date_after(text: str, label_pattern: str, default_year: int) -> str | None:
    for match in re.finditer(label_pattern, text, re.IGNORECASE):
        after = text[match.end() : min(len(text), match.end() + 90)]
        if "срок" in match.group(0).lower() or "погаш" in match.group(0).lower():
            term_match = re.search(r"[^0-9]{0,40}(\d+(?:[,.]\d+)?)\s?(?:года|год|лет)", after, re.IGNORECASE)
            if term_match:
                return f"{term_match.group(1).replace(',', '.')} years"
        parsed = extract_any_date(after, default_year)
        if parsed:
            return parsed

        start = max(0, match.start() - 45)
        parsed = extract_any_date(text[start : match.start()], default_year)
        if parsed:
            return parsed

    if "срок" in label_pattern:
        term_match = re.search(r"срок[^0-9]{0,40}(\d+(?:[,.]\d+)?)\s?(?:года|год|лет)", text, re.IGNORECASE)
        if term_match:
            return f"{term_match.group(1).replace(',', '.')} years"
    return None


def extract_any_date(text: str, default_year: int) -> str | None:
    numeric = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b", text)
    if numeric:
        day, month, year = numeric.groups()
        return normalize_date(day, month, year)

    month_names = "|".join(MONTHS)
    textual = re.search(rf"\b(\d{{1,2}})\s+({month_names})(?:\s+(20\d{{2}}))?\b", text, re.IGNORECASE)
    if textual:
        day, month_name, year = textual.groups()
        return normalize_date(day, str(MONTHS[month_name.lower()]), year or str(default_year))
    return None


def normalize_date(day: str, month: str, year: str) -> str:
    if len(year) == 2:
        year = "20" + year
    return f"{day.zfill(2)}.{month.zfill(2)}.{year}"


def extract_coupon_frequency(lowered: str) -> int | None:
    if "купонный период: 30" in lowered or "купонный период 30" in lowered:
        return 12
    if "купонный период: 91" in lowered or "купонный период 91" in lowered:
        return 4
    if "купонный период: 188" in lowered or "купонный период 188" in lowered:
        return 2
    if "ежемесяч" in lowered or "12 раз" in lowered or "12 куп" in lowered:
        return 12
    if "ежекварт" in lowered or "квартальн" in lowered or "4 раз" in lowered or "4 куп" in lowered:
        return 4
    if "полугод" in lowered or "2 раз" in lowered or "2 куп" in lowered:
        return 2
    return None


def extract_coupon_type(lowered: str, text: str) -> str:
    floating_markers = ("флоатер", "плавающ", "ключевая ставка", "кс +", "кс+", "офз +", "ruonia")
    fixed_markers = ("фиксирован", "постоянн", "фикс купон", "фикс ", "фикс на", "ежемесяч", "купон извест")
    if any(marker in lowered for marker in floating_markers):
        return "floating"
    if any(marker in lowered for marker in fixed_markers):
        return "fixed"
    if re.search(r"(?:купон|ставка купона|купоны)[^%\n]{0,80}\d{1,3}(?:[,.]\d{1,2})?\s?%", text, re.IGNORECASE):
        return "fixed"
    return "unknown"


def extract_offer(text: str) -> str | None:
    lowered = text.lower()
    if "оферта/погашение" in lowered:
        return None
    if "оферты нет" in lowered or "оферта: нет" in lowered or "без оферты" in lowered or "без оферт" in lowered:
        return "no"

    normalized_offers = extract_structured_offers(text)
    if normalized_offers:
        return "; ".join(normalized_offers)

    cleaned = re.sub(r"доходность\s+к\s+оферте\s*:\s*\d{1,3}(?:[,.]\d{1,2})?\s?%", "", lowered)
    match = re.search(r"оферт[аы]?(?:\s+put|\s+call)?[^.;\n]{0,80}", cleaned)
    return clean_sentence(match.group(0)) if match else None


def extract_structured_offers(text: str) -> list[str]:
    offers: list[str] = []

    for match in re.finditer(
        r"(?:(call|put)\s*-?\s*)?оферт[аы]?(?:\s*(put|call))?\s*:\s*(\d{1,2}\.\d{1,2}\.\d{2,4})",
        text,
        re.IGNORECASE,
    ):
        kind = normalize_offer_kind(match.group(1) or match.group(2))
        offers.append(f"{kind}-оферта: {normalize_offer_date(match.group(3))}")

    for match in re.finditer(
        r"оферт[аы]?\s*(put|call)?\s*:\s*[^.;\n]{0,80}?(через\s+\d+(?:[,.]\d+)?\s*(?:года|год|лет|мес\.?|месяц[а-я]*))",
        text,
        re.IGNORECASE,
    ):
        kind = normalize_offer_kind(match.group(1))
        offers.append(f"{kind}-оферта: {normalize_offer_relative(match.group(2))}")

    for match in re.finditer(
        r"на\s+(\d+(?:[,.]\d+)?\s*(?:года|год|лет|мес\.?|месяц[а-я]*))\s+до\s+оферты",
        text,
        re.IGNORECASE,
    ):
        offers.append(f"оферта: через {normalize_offer_relative(match.group(1))}")

    return dedupe_preserve_order(offers)


def normalize_offer_kind(value: str | None) -> str:
    if not value:
        return "оферта"
    lowered = value.lower()
    if lowered == "call":
        return "call"
    if lowered == "put":
        return "put"
    return "оферта"


def normalize_offer_date(value: str) -> str:
    day, month, year = value.split(".")
    return normalize_date(day, month, year)


def normalize_offer_relative(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace(",", ".")).strip()


def dedupe_preserve_order(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def extract_amortization(text: str) -> str | None:
    lowered = text.lower()
    if "амортизация не предусмотрена" in lowered or "без амортизац" in lowered or "амортизация: нет" in lowered:
        return "no"
    if "нет амортизац" in lowered:
        return "no"

    normalized = extract_structured_amortization(text)
    if normalized:
        return "; ".join(normalized)

    if "есть амортизац" in lowered:
        return "есть, детали нужно проверить"

    match = re.search(r"амортизац[^.;\n]{0,120}", text, re.IGNORECASE)
    return clean_sentence(match.group(0)).lower() if match else None


def extract_structured_amortization(text: str) -> list[str]:
    if "амортизац" not in text.lower():
        return []

    items: list[str] = []
    for date_value, percent in re.findall(
        r"(\d{1,2}\.\d{1,2}\.\d{2,4})\s*(?:-|–|—)\s*(\d{1,3}(?:[,.]\d{1,2})?)\s?%",
        text,
    ):
        items.append(f"{normalize_offer_date(date_value)} - {normalize_percent(percent)}")

    for match in re.finditer(
        r"амортизац[^.;\n]{0,80}?с\s+(\d{1,2}\.\d{1,2}\.\d{2,4})\s+по\s+(\d{1,3}(?:[,.]\d{1,2})?)\s?%\s+(кажд(?:ый|ые|ого)?\s+\d*\s*мес[а-я.]*)",
        text,
        re.IGNORECASE,
    ):
        items.append(
            f"с {normalize_offer_date(match.group(1))} по {normalize_percent(match.group(2))} {clean_sentence(match.group(3).lower())}"
        )

    for match in re.finditer(
        r"амортизац[^.;\n]{0,80}?(?:по\s+)?(\d{1,3}(?:[,.]\d{1,2})?)\s?%\s+в\s+([^.;\n]{0,80}?купон[а-я]*)",
        text,
        re.IGNORECASE,
    ):
        items.append(f"{normalize_percent(match.group(1))} в {clean_sentence(match.group(2).lower())}")

    return dedupe_preserve_order(items)


def clean_sentence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .,-:;")


def extract_qualified_only(lowered: str) -> bool | None:
    if "для квал" in lowered or "только квал" in lowered:
        return True
    if "для неквал" in lowered or "доступен неквал" in lowered:
        return False
    return None


def extract_issue_size(text: str) -> str | None:
    match = re.search(
        r"(?:объем|объём|сумма выпуска)[^.\n]{0,60}?((?:\$\s?)?\d+(?:\s?\d+)*(?:[,.]\d+)?\s?(?:млн|млрд)?\s?(?:руб|₽|\$)?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1).replace(",", ".")).strip()


def extract_issuer(text: str) -> str | None:
    explicit = re.search(r"эмитент\s*:\s*(.+?)(?:\n|кредитный рейтинг|параметры выпуска|$)", text, re.IGNORECASE)
    if explicit:
        return clean_name(explicit.group(1))

    quoted = re.search(r"(?:ООО|АО|ПАО)\s+[\"«]([^\"»]+)[\"»]", text, re.IGNORECASE)
    if quoted:
        return clean_name(quoted.group(1))

    first_line = first_meaningful_line(text)
    if first_line and looks_like_title(first_line):
        return clean_name(strip_issue_name(first_line))

    parenthetical = re.match(r"(.+?)\s*\(", text.strip())
    if parenthetical and looks_like_title(parenthetical.group(1)):
        return clean_name(strip_issue_name(parenthetical.group(1)))

    patterns = (
        r"экспорт[её]р[^-\n]*-\s*([^(\n]+)",
        r"выпуск облигаций\s+([^.,:;\n]+)",
        r"облигаци[ий]\s+([^.,:;\n]+)",
        r"флоатер\s+([^.,:;\n]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean_name(strip_issue_name(match.group(1)))
    return None


def first_meaningful_line(text: str) -> str | None:
    for line in text.splitlines():
        cleaned = line.strip(" -•●\t")
        if cleaned and not re.match(r"^(рейтинг|isin|ytm|стоимость|купон|дата|срок|объем|объём|выплаты)\b", cleaned, re.IGNORECASE):
            return trim_title_line(cleaned)
    return None


def trim_title_line(value: str) -> str:
    return re.split(
        r"\s+(?:Рейтинг|ISIN|Стоимость|YTM|Дата погашения|Купон|Ставка купона)\s*:",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()


def looks_like_title(value: str) -> bool:
    lowered = value.lower()
    if len(value) > 80:
        return False
    bad_markers = ("сейчас", "рассмотрим", "значение", "на ", "этот сервис", "фильтры")
    return not any(lowered.startswith(marker) for marker in bad_markers)


def extract_issue_name(text: str, issuer: str | None = None) -> str | None:
    original_match = re.search(
        r"\b(?:[ПP]\d{2}-[БB][ОO]-\d+|[БB][ОO]-\d{3}[РP]-\d+|\d{3}[РP]-\d+|[БB][ОO]-\d+|[БB][ПP]\d+|[БB][ПP]-\d+|[БB]\d[РP]\d+|\d[РP]\d+|\d[РP]-\d+|1P1|\d{5})\b",
        text,
        re.IGNORECASE,
    )
    if original_match:
        return original_match.group(0).upper().replace("P", "Р").replace("B", "Б").replace("O", "О")

    normalized = normalize_for_codes(text)
    match = re.search(
        r"\b(?:P\d{2}-BO-\d+|BO-\d{3}P-\d+|\d{3}P-\d+|BO-\d+|BP\d+|BP-\d+|B\dP\d+|\dP\d+|\dP-\d+|1P1|\d{5})\b",
        normalized,
        re.IGNORECASE,
    )
    if match:
        return restore_common_cyrillic_issue(match.group(0).upper())

    first_line = first_meaningful_line(text)
    if issuer and first_line:
        suffix = first_line.replace(issuer, "", 1).strip(" -:;")
        if suffix and len(suffix) <= 20 and re.search(r"\d", suffix):
            return suffix
    return None


def restore_common_cyrillic_issue(value: str) -> str:
    return value.replace("BO", "БО").replace("BP", "БП").replace("P", "Р")


def strip_issue_name(value: str) -> str:
    return re.sub(
        r"\b(?:[PП]\d{2}-[BБ][OО]-\d+|\d{3}[PР]-\d+|[BБ][OО]-\d{3}[PР]-\d+|[BБ][OО]-\d+|[BБ][PП]\d+|[BБ][PП]-\d+|\d[PР]\d+|\d[PР]-\d+|1P1|\d{5})\b",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def clean_name(value: str) -> str:
    value = re.sub(r"\b(?:ООО|АО|ПАО)\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\(?\bRU[0-9A-ZА-Я]{10}\b\)?", "", value, flags=re.IGNORECASE)
    value = strip_trailing_rating_group(value)
    value = value.strip().strip('"«»')
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .,-:;") or value.strip()


def strip_trailing_rating_group(value: str) -> str:
    while True:
        match = re.search(r"\s*\(([^()]*)\)\s*$", value)
        if not match or not is_rating_group(match.group(1)):
            return value
        value = value[: match.start()]


def find_missing_fields(instrument: dict[str, Any], terms: dict[str, Any]) -> set[str]:
    missing: set[str] = set()
    for field in CRITICAL_FIELDS:
        source = instrument if field in instrument else terms
        if source.get(field) in (None, "", "unknown"):
            missing.add(field)
    return missing


def collect_red_flags(instrument: dict[str, Any], terms: dict[str, Any], lowered: str) -> list[str]:
    flags: list[str] = []
    if terms["coupon_type"] == "floating":
        flags.append("floating_coupon")
    if terms["offer"] and terms["offer"] != "no":
        flags.append("offer_present_or_needs_review")
    if terms["amortization"] and terms["amortization"] != "no":
        flags.append("amortization_present_or_needs_review")
    if terms["qualified_only"] is True:
        flags.append("qualified_investors_only")
    if rating_below_target(instrument.get("rating")):
        flags.append("rating_below_target")
    if "доход до" in lowered and not terms["ytm"]:
        flags.append("promotional_yield_without_ytm")
    if "маленький выпуск" in lowered or "низкая ликвид" in lowered:
        flags.append("liquidity_or_size_risk")
    if "$" in lowered or "доллар" in lowered or "usd" in lowered:
        flags.append("currency_mismatch_or_fx_linked")
    return flags


def rating_below_target(rating: str | None) -> bool:
    if rating is None:
        return False
    normalized = normalize_for_codes(rating).upper().removeprefix("RU")
    if normalized.startswith(("AAA", "AA", "A", "BBB")):
        return False
    return normalized.startswith(("BB", "B", "CCC", "CC", "C"))


def classify_signal_type(text: str, lowered: str, terms: dict[str, Any]) -> str:
    if terms["book_building_date"] or terms["placement_date"] or "размещ" in lowered or "сбор заявок" in lowered:
        return "new_placement"
    if extract_isin(text) or terms["maturity_date"]:
        return "secondary_idea"
    if any(marker in lowered for marker in ("дефолт", "пересмотр рейтинга", "снижение рейтинга", "реструктуризац")):
        return "risk_news"
    return "unknown"


def classify_status(missing_fields: list[str], red_flags: list[str], terms: dict[str, Any]) -> str:
    if "floating_coupon" in red_flags:
        return "reject"
    if "qualified_investors_only" in red_flags:
        return "reject"
    if len(missing_fields) >= 6:
        return "needs_review"
    if red_flags:
        return "needs_review"
    if terms["coupon_frequency_per_year"] == 12 and terms["offer"] == "no" and terms["amortization"] == "no":
        return "interesting"
    return "needs_review"


def build_reason(status: str, red_flags: list[str], terms: dict[str, Any], signal_type: str) -> str:
    if status == "reject":
        return "Есть жесткий стоп-фактор для базовой стратегии."
    if red_flags:
        return "Есть признаки интересного выпуска, но нужны ручная проверка и сверка красных флагов."
    if signal_type == "secondary_idea":
        return "Похоже на идею по уже торгующейся бумаге; нужна ручная сверка параметров и ликвидности."
    if terms["coupon_frequency_per_year"] == 12:
        return "Похоже на выпуск под базовую стратегию: ежемесячный купон и без явных красных флагов."
    return "Пост похож на релевантный выпуск, но часть условий нужно проверить вручную."


if __name__ == "__main__":
    main()
