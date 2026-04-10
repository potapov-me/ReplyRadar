"""LiteLLM wrapper — единая точка входа для всех LLM-вызовов.

Таксономия ошибок (ADR-0011):
  TransientLLMError  — сеть, timeout, временная недоступность → retry
  PermanentLLMError  — невалидный ответ, превышен контекст → quarantine после N попыток
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

import litellm
from pydantic import ValidationError

from replyradar.llm.contracts.classify import ClassifyResponse
from replyradar.llm.contracts.extract import ExtractResponse
from replyradar.llm.prompts.classify import CLASSIFY_SYSTEM, CLASSIFY_USER
from replyradar.llm.prompts.extract import EXTRACT_SYSTEM, EXTRACT_USER

if TYPE_CHECKING:
    from ..config import EmbeddingConfig, LLMConfig

logger = logging.getLogger(__name__)

# LiteLLM пишет много INFO-логов, снижаем до WARNING
litellm.suppress_debug_info = True


def _build_user_message(
    template: str,
    *,
    sender_name: str | None,
    text: str,
    context: list[dict[str, str | None]] | None,
) -> str:
    """Формирует user-сообщение для LLM, добавляя историю беседы при наличии."""
    target = template.format(sender_name=sender_name or "unknown", text=text or "")
    if not context:
        return target
    history_lines = [
        f"{m.get('sender_name') or 'unknown'}: {m.get('text') or ''}" for m in context
    ]
    history_block = "\n".join(history_lines)
    return f"[Previous messages for context]\n{history_block}\n\n[Message to analyze]\n{target}"


class LLMError(Exception):
    """Базовый класс ошибок LLM."""

    error_class: str = "unknown"


class TransientLLMError(LLMError):
    """Временная ошибка: timeout, сеть, Postgres-сброс соединения."""

    error_class = "transient"


class PermanentLLMError(LLMError):
    """Постоянная ошибка: невалидный ответ, нарушение контракта."""

    error_class = "permanent"


# Исключения litellm/openai, которые считаем временными
_TRANSIENT_EXCEPTIONS = (
    litellm.Timeout,  # type: ignore[attr-defined]
    litellm.ServiceUnavailableError,  # type: ignore[attr-defined]
    litellm.APIConnectionError,  # type: ignore[attr-defined]
    litellm.RateLimitError,  # type: ignore[attr-defined]
    litellm.InternalServerError,  # type: ignore[attr-defined]
)


def _llm_model_str(config: LLMConfig) -> str:
    """LiteLLM требует формат 'openai/<model>' для OpenAI-совместимых провайдеров."""
    return f"openai/{config.model}"


def _emb_model_str(config: EmbeddingConfig) -> str:
    return f"openai/{config.model}"


class LLMClient:
    def __init__(self, llm_config: LLMConfig, embedding_config: EmbeddingConfig) -> None:
        self._llm = llm_config
        self._emb = embedding_config

    async def check_health(self) -> bool:
        """Проверяет доступность LM Studio. Не бросает исключений."""
        try:
            await litellm.aembedding(
                model=_emb_model_str(self._emb),
                input=["ping"],
                api_base=self._emb.base_url,
                api_key="lm-studio",
            )
            return True
        except Exception:  # pylint: disable=broad-exception-caught
            return False

    async def classify(
        self,
        text: str,
        sender_name: str | None = None,
        context: list[dict[str, str | None]] | None = None,
    ) -> ClassifyResponse:
        """Классифицирует сообщение: signal vs. noise.

        Raises:
            TransientLLMError: если LM Studio временно недоступен.
            PermanentLLMError: если ответ не прошёл Pydantic-контракт.
        """
        user_msg = _build_user_message(
            CLASSIFY_USER,
            sender_name=sender_name,
            text=text,
            context=context,
        )
        raw = await self._complete(CLASSIFY_SYSTEM, user_msg, stage="classify")
        return self._parse(ClassifyResponse, raw)

    async def extract(
        self,
        text: str,
        sender_name: str | None = None,
        context: list[dict[str, str | None]] | None = None,
    ) -> ExtractResponse:
        """Извлекает commitments, pending_replies, communication_risks из сообщения.

        Raises:
            TransientLLMError / PermanentLLMError — аналогично classify().
        """
        user_msg = _build_user_message(
            EXTRACT_USER,
            sender_name=sender_name,
            text=text,
            context=context,
        )
        raw = await self._complete(EXTRACT_SYSTEM, user_msg, stage="extract")
        return self._parse(ExtractResponse, raw)

    async def embed(self, text: str) -> list[float]:
        """Возвращает вектор эмбеддинга для текста.

        Raises:
            TransientLLMError / PermanentLLMError.
        """
        try:
            response = await litellm.aembedding(
                model=_emb_model_str(self._emb),
                input=[text],
                api_base=self._emb.base_url,
                api_key="lm-studio",
            )
            return list(response.data[0]["embedding"])
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientLLMError(f"embedding transient: {exc}") from exc
        except Exception as exc:
            raise PermanentLLMError(f"embedding permanent: {exc}") from exc

    # ── internal ──────────────────────────────────────────────────────────────

    async def _complete(self, system: str, user: str) -> str:
        """Вызывает LLM и возвращает текст ответа."""
        try:
            resp: Any = await litellm.acompletion(
                model=_llm_model_str(self._llm),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                api_base=self._llm.base_url,
                api_key=self._llm.api_key,
                temperature=0.0,
            )
            return resp.choices[0].message.content or ""
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientLLMError(f"completion transient: {exc}") from exc
        except Exception as exc:
            raise PermanentLLMError(f"completion permanent: {exc}") from exc

    @staticmethod
    def _parse[T](model: type[T], raw: str) -> T:
        """Парсит JSON-ответ в Pydantic-модель.

        Raises:
            PermanentLLMError при невалидном JSON или нарушении контракта.
        """
        # Вырезаем json-блок из markdown-обёртки, если модель добавила ```json
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(line for line in lines if not line.startswith("```")).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PermanentLLMError(
                f"schema_validation: не удалось разобрать JSON: {exc!r}. Raw: {raw[:200]!r}"
            ) from exc

        try:
            return model(**data)
        except (ValidationError, TypeError) as exc:
            raise PermanentLLMError(
                f"schema_validation: контракт нарушен: {exc!r}. Raw: {raw[:200]!r}"
            ) from exc
