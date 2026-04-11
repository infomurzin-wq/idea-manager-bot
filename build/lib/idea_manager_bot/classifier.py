from __future__ import annotations

import re

from idea_manager_bot.llm import LLMService
from idea_manager_bot.project_registry import ProjectTarget


EXPLICIT_MAPPINGS = {
    "ставки": "ufc-betting",
    "ufc": "ufc-betting",
    "венчур": "venture-investing",
    "инвестиции": "venture-investing",
    "программирование": "learning-programming",
    "код": "learning-programming",
    "банк": "bank-factoring-product",
    "факторинг": "bank-factoring-product",
    "shared": "shared",
}


def detect_explicit_project(text: str) -> str | None:
    pattern = re.compile(r"(?:проект|раздел|категория)\s*:\s*([A-Za-z0-9\-_а-яА-Я]+)", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None

    value = match.group(1).strip().lower()
    if value in EXPLICIT_MAPPINGS:
        return EXPLICIT_MAPPINGS[value]
    return value


def classify_project(
    text: str,
    registry: dict[str, ProjectTarget],
    llm_service: LLMService | None = None,
) -> tuple[str, str]:
    normalized = text.lower()

    explicit = detect_explicit_project(normalized)
    if explicit in registry:
        return explicit, "explicit"

    scores: dict[str, int] = {}
    for project_key, project in registry.items():
        score = 0
        for keyword in project.keywords:
            if keyword and keyword in normalized:
                score += 1
        scores[project_key] = score

    best_project = max(scores, key=scores.get)
    if scores[best_project] > 0:
        return best_project, "keywords"

    if llm_service and llm_service.available:
        llm_choice = llm_service.classify_project(text, registry)
        if llm_choice in registry:
            return llm_choice, "llm"

    return "shared", "fallback"
