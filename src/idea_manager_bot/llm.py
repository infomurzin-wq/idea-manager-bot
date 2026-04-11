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
