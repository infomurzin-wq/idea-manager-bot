from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectTarget:
    key: str
    label: str
    inbox_dir: Path
    context_dir: Path
    description: str
    keywords: tuple[str, ...]


def build_project_registry(workspace_root: Path) -> dict[str, ProjectTarget]:
    return {
        "ufc-betting": ProjectTarget(
            key="ufc-betting",
            label="UFC Betting",
            inbox_dir=workspace_root / "ufc-betting" / "01_inbox" / "ideas",
            context_dir=workspace_root / "ufc-betting" / "01_inbox" / "context",
            description="Идеи по ставкам, боям, моделям, аналитике и дисциплине банка.",
            keywords=("ставк", "ufc", "бой", "коэфф", "букмек", "банкрол", "файт", "тотал"),
        ),
        "venture-investing": ProjectTarget(
            key="venture-investing",
            label="Venture Investing",
            inbox_dir=workspace_root / "venture-investing" / "01_inbox" / "ideas-cards",
            context_dir=workspace_root / "venture-investing" / "01_inbox" / "context-cards",
            description="Инвестиционные идеи, рынки, компании, сделки и исследовательские гипотезы.",
            keywords=("стартап", "венчур", "рынок", "инвест", "deal", "fund", "saas", "компан"),
        ),
        "learning-programming": ProjectTarget(
            key="learning-programming",
            label="Learning Programming",
            inbox_dir=workspace_root / "learning-programming" / "01_inbox" / "ideas",
            context_dir=workspace_root / "learning-programming" / "01_inbox" / "context",
            description="Идеи по обучению программированию, ботам, pet-проектам и техэкспериментам.",
            keywords=("python", "код", "бот", "api", "программ", "разработ", "telegram", "автоматизац"),
        ),
        "bank-factoring-product": ProjectTarget(
            key="bank-factoring-product",
            label="Bank Factoring Product",
            inbox_dir=workspace_root / "bank-factoring-product" / "01_inbox" / "ideas",
            context_dir=workspace_root / "bank-factoring-product" / "01_inbox" / "context",
            description="Продуктовые гипотезы, процессы, UX, проверки и рабочие улучшения.",
            keywords=("банк", "факторинг", "продукт", "клиент", "интерфейс", "оплат", "метрик", "процесс"),
        ),
        "shared": ProjectTarget(
            key="shared",
            label="Shared",
            inbox_dir=workspace_root / "shared" / "01_inbox" / "ideas",
            context_dir=workspace_root / "shared" / "01_inbox" / "context",
            description="Временное место для идей, которые пока не удалось уверенно классифицировать.",
            keywords=(),
        ),
    }
