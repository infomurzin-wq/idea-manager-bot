from __future__ import annotations

import logging
from pathlib import Path

from openai import OpenAI

from idea_manager_bot.project_registry import ProjectTarget

LOGGER = logging.getLogger(__name__)


class LLMService:
    def __init__(self, api_key: str | None, model: str) -> None:
        self.available = bool(api_key)
        self.model = model
        self.client = OpenAI(api_key=api_key) if api_key else None

    def classify_project(self, text: str, registry: dict[str, ProjectTarget]) -> str | None:
        if not self.client:
            return None

        try:
            options = "\n".join(f"- {item.key}: {item.description}" for item in registry.values())
            response = self.client.responses.create(
                model=self.model,
                input=(
                    "Выбери один project key для идеи.\n"
                    "Верни только один ключ без пояснений.\n\n"
                    f"Варианты:\n{options}\n\n"
                    f"Идея:\n{text}"
                ),
            )
            result = (response.output_text or "").strip()
            return result if result in registry else None
        except Exception:  # noqa: BLE001
            LOGGER.exception("LLM classify_project failed")
            return None

    def analyze_idea(self, text: str, project: ProjectTarget, project_context: str, comments: list[str]) -> str:
        if not self.client:
            return self._fallback_analysis(text, project, comments)

        comments_block = "\n".join(f"- {item}" for item in comments) if comments else "- комментариев пока нет"
        prompt = (
            "Ты помогаешь развивать идеи кратко и практично.\n"
            "Ответь на русском языке в Markdown.\n"
            "Структура ответа строго такая:\n"
            "## Усиление идеи\n"
            "## Что в ней сильного\n"
            "## Что вызывает сомнения\n"
            "## Как проверить быстро\n"
            "## Следующий лучший шаг\n\n"
            f"Проект: {project.label}\n"
            f"Описание проекта: {project.description}\n\n"
            f"Контекст проекта:\n{project_context[:5000]}\n\n"
            f"Идея:\n{text}\n\n"
            f"Комментарии и продолжение мысли:\n{comments_block}"
        )
        try:
            response = self.client.responses.create(model=self.model, input=prompt)
            return (response.output_text or "").strip()
        except Exception:  # noqa: BLE001
            LOGGER.exception("LLM analyze_idea failed, using fallback")
            return self._fallback_analysis(text, project, comments)

    def summarize_context(self, text: str, project: ProjectTarget, project_context: str) -> str:
        if not self.client:
            return self._fallback_summary(text, project)

        prompt = (
            "Сделай краткое практичное summary контекста на русском языке в Markdown.\n"
            "Структура ответа строго такая:\n"
            "## О чём материал\n"
            "## Ключевые мысли\n"
            "## Почему это важно для проекта\n"
            "## Что стоит запомнить\n\n"
            f"Проект: {project.label}\n"
            f"Описание проекта: {project.description}\n\n"
            f"Контекст проекта:\n{project_context[:5000]}\n\n"
            f"Материал:\n{text}"
        )
        try:
            response = self.client.responses.create(model=self.model, input=prompt)
            return (response.output_text or "").strip()
        except Exception:  # noqa: BLE001
            LOGGER.exception("LLM summarize_context failed, using fallback")
            return self._fallback_summary(text, project)

    def research_bond(self, question: str, card_context: str, history: list[dict] | None = None) -> str:
        if not self.client:
            return (
                "OpenAI API key не настроен, поэтому Research Mode сейчас недоступен. "
                "Карточка и вопрос сохранены в боте, но внешний поиск и LLM-ответ выполнить нельзя."
            )

        history_block = self._format_research_history(history or [])
        prompt = (
            "Ты аналитический помощник по российским облигациям для личного ресерча пользователя.\n"
            "Ответь на русском языке. Это не индивидуальная инвестиционная рекомендация.\n"
            "Используй веб-поиск для актуальной информации, если инструмент доступен.\n"
            "Опирайся на карточку, но проверяй эмитента, новости, рейтинг, параметры выпуска и риски по открытым источникам.\n"
            "Если данных не хватает или источник не найден, прямо напиши, что нужно проверить вручную.\n"
            "Структура ответа:\n"
            "1. Короткий вывод\n"
            "2. Что удалось проверить\n"
            "3. Риски и красные флаги\n"
            "4. Что спросить/проверить дальше\n"
            "5. Источники\n\n"
            f"Карточка:\n{card_context[:6000]}\n\n"
            f"История research по карточке:\n{history_block}\n\n"
            f"Вопрос пользователя:\n{question}"
        )
        for tool_type in ("web_search", "web_search_preview"):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    input=prompt,
                    tools=[{"type": tool_type}],
                )
                return (response.output_text or "").strip()
            except Exception:  # noqa: BLE001
                LOGGER.exception("LLM research_bond failed with tool=%s", tool_type)

        try:
            response = self.client.responses.create(model=self.model, input=prompt)
            answer = (response.output_text or "").strip()
            return (
                "Веб-поиск не сработал, ниже ответ только по данным карточки и знаниям модели.\n\n"
                f"{answer}"
            ).strip()
        except Exception:  # noqa: BLE001
            LOGGER.exception("LLM research_bond failed")
            return (
                "Не удалось выполнить Research Mode через OpenAI API. "
                "Попробуй повторить вопрос позже или проверь настройки OPENAI_API_KEY/модели."
            )

    def transcribe_audio(self, file_path: Path) -> str:
        if not self.client:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        with file_path.open("rb") as audio_file:
            transcript = self.client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio_file,
            )
        return transcript.text.strip()

    @staticmethod
    def _format_research_history(history: list[dict]) -> str:
        if not history:
            return "- истории пока нет"
        lines: list[str] = []
        for item in history[-5:]:
            question = str(item.get("question") or "").strip()
            answer = str(item.get("answer") or "").strip()
            created_at = str(item.get("created_at") or "").strip()
            lines.append(f"- {created_at} Вопрос: {question[:500]}")
            if answer:
                lines.append(f"  Ответ: {answer[:1200]}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_analysis(text: str, project: ProjectTarget, comments: list[str]) -> str:
        latest_comment = comments[-1] if comments else "Комментариев пока нет."
        comments_count = len(comments)
        comment_effect_block = (
            "## Что изменилось после комментария\n"
            f"- Новый комментарий: {latest_comment}\n"
            "- Пересобери гипотезу так, чтобы этот комментарий стал явным ограничением или критерием.\n"
            "- Добавь один проверочный шаг именно под новый комментарий.\n\n"
            if comments
            else ""
        )
        return (
            "## Усиление идеи\n"
            f"Сформулируй идею для проекта `{project.key}` через цель, гипотезу ценности и понятный результат. "
            "Добавь один конкретный сценарий использования и критерий успеха.\n\n"
            f"{comment_effect_block}"
            "## Что в ней сильного\n"
            "- Есть исходный импульс для действия.\n"
            "- Идею уже можно привязать к существующему проекту и рабочей базе.\n"
            "- Её можно быстро превратить в проверяемую гипотезу.\n\n"
            "## Что вызывает сомнения\n"
            "- Пока не хватает численного критерия успеха.\n"
            "- Не до конца ясно, что именно является главным риском.\n"
            "- Может смешиваться сама идея и способ реализации.\n\n"
            "## Как проверить быстро\n"
            "- Сформулировать одну проверяемую гипотезу.\n"
            "- Определить, какие данные или сигналы подтвердят ценность.\n"
            "- Зафиксировать самый дешёвый следующий тест.\n\n"
            "## Следующий лучший шаг\n"
            f"Перепиши идею в одном абзаце и обнови её с учётом последнего комментария. "
            f"Комментариев в истории: {comments_count}. Последний комментарий: {latest_comment}\n\n"
            f"Исходный текст идеи:\n{text}"
        )

    @staticmethod
    def _fallback_summary(text: str, project: ProjectTarget) -> str:
        preview = text[:1400]
        return (
            "## О чём материал\n"
            f"Это контекст для проекта `{project.key}`. Его стоит воспринимать как источник знаний или внешнее наблюдение.\n\n"
            "## Ключевые мысли\n"
            "- В материале есть полезный сигнал, который стоит учитывать в проекте.\n"
            "- Его лучше использовать как фон для решений и новых идей.\n"
            "- При необходимости из него можно позже сделать отдельную идею.\n\n"
            "## Почему это важно для проекта\n"
            "- Контекст помогает принимать решения не в вакууме.\n"
            "- Он сохраняет внешние наблюдения рядом с рабочими материалами.\n\n"
            "## Что стоит запомнить\n"
            f"{preview}"
        )
