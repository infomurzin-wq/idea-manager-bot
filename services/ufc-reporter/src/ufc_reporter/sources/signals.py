from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from lxml import html as lxml_html

from ..models import FightResultEntry, PreFightSignal
from .http import fetch_text


@dataclass(frozen=True)
class EspnNewsArticle:
    title: str
    url: str
    published_hint: str


def build_pre_fight_signals(
    *,
    fighter_name: str,
    overview_url: str,
    event_weight_class: str,
    event_date: str,
    player_header: dict[str, Any],
    last_five: list[FightResultEntry],
) -> list[PreFightSignal]:
    signals: list[PreFightSignal] = []
    seen: set[tuple[str, str]] = set()

    for signal in _deterministic_signals(
        fighter_name=fighter_name,
        event_weight_class=event_weight_class,
        event_date=event_date,
        player_header=player_header,
        last_five=last_five,
    ):
        key = (signal.signal_type, signal.summary_ru)
        if key not in seen:
            signals.append(signal)
            seen.add(key)

    for signal in _headline_signals(fighter_name=fighter_name, overview_url=overview_url):
        key = (signal.signal_type, signal.summary_ru)
        if key not in seen:
            signals.append(signal)
            seen.add(key)

    if not signals:
        return [
            PreFightSignal(
                summary_ru="Существенных предбоевых сигналов не найдено.",
                source="n/a",
                signal_type="none",
            )
        ]
    return signals[:3]


def _deterministic_signals(
    *,
    fighter_name: str,
    event_weight_class: str,
    event_date: str,
    player_header: dict[str, Any],
    last_five: list[FightResultEntry],
) -> list[PreFightSignal]:
    signals: list[PreFightSignal] = []
    athlete = player_header.get("ath", {})
    listed_weight_class = athlete.get("wghtclss", "").strip()
    normalized_event_class = _normalize_weight_class(event_weight_class)
    normalized_listed_class = _normalize_weight_class(listed_weight_class)

    if (
        normalized_event_class
        and normalized_listed_class
        and normalized_event_class != normalized_listed_class
    ):
        signals.append(
            PreFightSignal(
                summary_ru=(
                    f"У {fighter_name} есть весовой контекст: в профиле ESPN текущим классом указан "
                    f"`{listed_weight_class}`, а текущий бой заявлен как `{event_weight_class}`."
                ),
                source="[ESPN profile data](https://www.espn.com)",
                signal_type="weight_class_context",
            )
        )

    if last_five and event_date != "n/a":
        event_dt = _safe_date(event_date)
        last_fight_dt = _safe_date(last_five[0].fight_date)
        if event_dt and last_fight_dt:
            gap_days = (event_dt - last_fight_dt).days
            if gap_days >= 240:
                signals.append(
                    PreFightSignal(
                        summary_ru=(
                            f"У {fighter_name} заметный простой перед боем: последний зафиксированный по ESPN выход был "
                            f"`{last_five[0].fight_date}`, это примерно `{gap_days}` дней до текущего ивента."
                        ),
                        source="ESPN fight history",
                        signal_type="layoff",
                    )
                )
            elif 0 < gap_days <= 49:
                signals.append(
                    PreFightSignal(
                        summary_ru=(
                            f"У {fighter_name} короткий разворот между боями: между последним поединком "
                            f"`{last_five[0].fight_date}` и текущим ивентом около `{gap_days}` дней."
                        ),
                        source="ESPN fight history",
                        signal_type="short_turnaround",
                    )
                )

    ufc_count = sum(1 for fight in last_five if fight.promotion == "UFC")
    if last_five and ufc_count <= 1:
        signals.append(
            PreFightSignal(
                summary_ru=(
                    f"У {fighter_name} ограниченная свежая выборка на уровне UFC: только `{ufc_count}` бой из последних "
                    f"`{len(last_five)}` прошёл под баннером UFC."
                ),
                source="ESPN fight history",
                signal_type="sample_quality",
            )
        )

    return signals


def _headline_signals(*, fighter_name: str, overview_url: str) -> list[PreFightSignal]:
    news_url = _espn_news_url(overview_url)
    if not news_url:
        return []
    try:
        page_html = fetch_text(news_url, cache_namespace="espn-news")
    except Exception:
        return []

    articles = _parse_espn_news_articles(page_html, base_url=news_url)
    name_tokens = _name_tokens(fighter_name)
    signals: list[PreFightSignal] = []
    for article in articles[:12]:
        lowered = article.title.lower()
        if not any(token in lowered for token in name_tokens):
            continue
        keyword_match = _headline_keyword_match(lowered)
        if not keyword_match:
            continue
        signal_type, summary_prefix = keyword_match
        signals.append(
            PreFightSignal(
                summary_ru=f"{summary_prefix}: `{article.title}`.",
                source=f"[ESPN news]({article.url})",
                signal_type=signal_type,
            )
        )
    return signals


def _espn_news_url(overview_url: str) -> str:
    if "/fighter/_/" not in overview_url:
        return ""
    return overview_url.replace("/fighter/_/", "/fighter/news/_/")


def _parse_espn_news_articles(page_html: str, *, base_url: str) -> list[EspnNewsArticle]:
    document = lxml_html.fromstring(page_html)
    articles: list[EspnNewsArticle] = []
    for node in document.xpath("//article[contains(@class, 'contentItem')]"):
        title_nodes = node.xpath(".//h2[contains(@class, 'contentItem__title')]")
        link_nodes = node.xpath(".//a[@href][1]")
        if not title_nodes or not link_nodes:
            continue
        title = " ".join(title_nodes[0].itertext()).strip()
        href = link_nodes[0].get("href", "").strip()
        if not title or not href:
            continue
        published_hint = ""
        time_nodes = node.xpath(".//*[contains(@class, 'time-elapsed')]")
        if time_nodes:
            published_hint = " ".join(time_nodes[0].itertext()).strip()
        articles.append(
            EspnNewsArticle(
                title=title,
                url=urljoin(base_url, href),
                published_hint=published_hint,
            )
        )
    return articles


def _headline_keyword_match(title_lower: str) -> tuple[str, str] | None:
    keyword_groups = [
        ("injury", "Есть injury/recovery контекст", ("injury", "injured", "surgery", "hospital", "consciousness", "recovery", "recover")),
        ("weight", "Есть весовой контекст", ("weight", "weight cut", "miss weight", "move up", "move down", "flyweight", "bantamweight", "featherweight", "lightweight", "welterweight", "middleweight", "heavyweight")),
        ("replacement", "Есть контекст замены/short notice", ("short notice", "replacement", "withdraw", "withdraws", "pullout", "steps in", "new opponent")),
        ("camp", "Есть контекст лагеря или подготовки", ("camp", "team", "coach")),
        ("layoff", "Есть контекст возвращения после паузы", ("returns", "return", "back after", "comeback", "layoff")),
    ]
    for signal_type, label, keywords in keyword_groups:
        if any(keyword in title_lower for keyword in keywords):
            return signal_type, label
    return None


def _name_tokens(fighter_name: str) -> set[str]:
    tokens = {fighter_name.lower()}
    cleaned = (
        fighter_name.lower()
        .replace(".", " ")
        .replace("-", " ")
        .replace("'", " ")
    )
    for token in cleaned.split():
        if len(token) >= 4:
            tokens.add(token)
    return tokens


def _normalize_weight_class(value: str) -> str:
    cleaned = value.lower().strip()
    if " - " in cleaned:
        cleaned = cleaned.split(" - ", 1)[0]
    return cleaned


def _safe_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None
