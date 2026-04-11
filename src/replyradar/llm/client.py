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

from replyradar.llm.contracts.classify import ClassifyBatchItem, ClassifyResponse
from replyradar.llm.contracts.extract import ExtractResponse
from replyradar.llm.prompts.classify import (
    CLASSIFY_BATCH_SYSTEM,
    CLASSIFY_BATCH_USER,
    CLASSIFY_SYSTEM,
    CLASSIFY_USER,
)
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
    """Временная ошибка конкретного сообщения: rate limit, разовый сбой."""

    error_class = "transient"


class LLMUnavailableError(TransientLLMError):
    """LLM-сервис недоступен целиком: не запущен, нет модели, обрыв соединения.

    Отличие от TransientLLMError: проблема не в конкретном сообщении, а в инфраструктуре.
    Engine при получении этой ошибки должен остановить обработку и ждать восстановления.
    """

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

# Фрагменты сообщений об ошибках LM Studio, которые являются временными,
# но приходят как BadRequestError (HTTP 400)
_TRANSIENT_LM_STUDIO_MESSAGES = (
    "No models loaded",  # модель не загружена, но LM Studio запущена
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
        msg_id: int | None = None,
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
        # max_tokens не ограничиваем: модели с thinking mode (Qwen3, DeepSeek-R1)
        # расходуют сотни токенов на внутренние рассуждения до JSON-ответа,
        # и жёсткий лимит обрезает вывод до пустой строки.
        raw = await self._complete(CLASSIFY_SYSTEM, user_msg, stage="classify", msg_id=msg_id)
        return self._parse(ClassifyResponse, raw)

    async def classify_batch(
        self,
        messages: list[dict[str, str | None]],
    ) -> list[ClassifyBatchItem | None]:
        """Batch-классификация: один LLM-вызов на весь список сообщений.

        Возвращает list той же длины, что messages.
        Элемент None означает, что результат для этого индекса отсутствует или невалиден.

        Raises:
            LLMUnavailableError: LM Studio недоступен.
            PermanentLLMError: ответ — не JSON-массив (полный сбой парсинга).
        """
        n = len(messages)
        items_lines = []
        for i, m in enumerate(messages, start=1):
            sender = m.get("sender_name") or "unknown"
            # Сворачиваем переносы строк — в inline-формате батча они мешают
            text = (m.get("text") or "").replace("\n", " ").strip()
            items_lines.append(f"[{i}] Sender: {sender} | Message: {text}")

        user_msg = CLASSIFY_BATCH_USER.format(items="\n".join(items_lines))
        # ~60 токенов на результат + 300 на thinking-overhead (Qwen3, DeepSeek-R1).
        # Без запаса на thinking модель обрезается посередине JSON-массива.
        max_tokens = n * 60 + 300
        raw = await self._complete(
            CLASSIFY_BATCH_SYSTEM,
            user_msg,
            stage="classify_batch",
            max_tokens=max_tokens,
        )
        return self._parse_batch_classify(raw, n)

    async def extract(
        self,
        text: str,
        sender_name: str | None = None,
        context: list[dict[str, str | None]] | None = None,
        msg_id: int | None = None,
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
        raw = await self._complete(EXTRACT_SYSTEM, user_msg, stage="extract", msg_id=msg_id)
        return self._parse(ExtractResponse, raw)

    async def embed(self, text: str, msg_id: int | None = None) -> list[float]:
        """Возвращает вектор эмбеддинга для текста.

        Raises:
            TransientLLMError / PermanentLLMError.
        """
        t0 = time.monotonic()
        try:
            response = await litellm.aembedding(
                model=_emb_model_str(self._emb),
                input=[text],
                api_base=self._emb.base_url,
                api_key="lm-studio",
            )
            vector: list[float] = list(response.data[0]["embedding"])
            logger.info(
                "llm.embed ok msg_id=%s duration=%.3fs dims=%d model=%s",
                msg_id,
                time.monotonic() - t0,
                len(vector),
                self._emb.model,
            )
            return vector
        except _TRANSIENT_EXCEPTIONS as exc:
            logger.critical("llm unavailable stage=embed msg_id=%s duration=%.3fs: %s", msg_id, time.monotonic() - t0, exc)
            raise LLMUnavailableError(f"embedding unavailable: {exc}") from exc
        except Exception as exc:
            if any(msg in str(exc) for msg in _TRANSIENT_LM_STUDIO_MESSAGES):
                logger.critical(
                    "llm unavailable stage=embed msg_id=%s duration=%.3fs: %s", msg_id, time.monotonic() - t0, exc
                )
                raise LLMUnavailableError(f"embedding unavailable: {exc}") from exc
            logger.warning("llm.embed permanent msg_id=%s duration=%.3fs: %s", msg_id, time.monotonic() - t0, exc)
            raise PermanentLLMError(f"embedding permanent: {exc}") from exc

    # ── internal ──────────────────────────────────────────────────────────────

    async def _complete(
        self,
        system: str,
        user: str,
        *,
        stage: str = "complete",
        msg_id: int | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Вызывает LLM и возвращает текст ответа."""
        t0 = time.monotonic()
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
                **({"max_tokens": max_tokens} if max_tokens is not None else {}),
            )
            duration = time.monotonic() - t0
            usage = getattr(resp, "usage", None)
            if usage:
                logger.info(
                    "llm.%s ok msg_id=%s duration=%.3fs tokens_in=%d tokens_out=%d model=%s",
                    stage,
                    msg_id,
                    duration,
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    self._llm.model,
                )
            else:
                logger.info("llm.%s ok msg_id=%s duration=%.3fs model=%s", stage, msg_id, duration, self._llm.model)
            return resp.choices[0].message.content or ""
        except _TRANSIENT_EXCEPTIONS as exc:
            logger.critical(
                "llm unavailable stage=%s msg_id=%s duration=%.3fs: %s", stage, msg_id, time.monotonic() - t0, exc
            )
            raise LLMUnavailableError(f"completion unavailable: {exc}") from exc
        except Exception as exc:
            if any(msg in str(exc) for msg in _TRANSIENT_LM_STUDIO_MESSAGES):
                logger.critical(
                    "llm unavailable stage=%s msg_id=%s duration=%.3fs: %s",
                    stage,
                    msg_id,
                    time.monotonic() - t0,
                    exc,
                )
                raise LLMUnavailableError(f"completion unavailable: {exc}") from exc
            logger.warning(
                "llm.%s permanent msg_id=%s duration=%.3fs: %s", stage, msg_id, time.monotonic() - t0, exc
            )
            raise PermanentLLMError(f"completion permanent: {exc}") from exc

    @staticmethod
    def _parse_batch_classify(raw: str, n: int) -> list[ClassifyBatchItem | None]:
        """Парсит batch-ответ классификации.

        Возвращает list длиной n; элемент None — результат отсутствует или невалиден.
        Бросает PermanentLLMError, если ответ не является JSON-массивом вовсе.
        """
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(line for line in lines if not line.startswith("```")).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PermanentLLMError(
                f"classify_batch: не удалось разобрать JSON: {exc!r}. Raw: {raw[:300]!r}"
            ) from exc

        if not isinstance(data, list):
            raise PermanentLLMError(
                f"classify_batch: ожидался массив, получен "
                f"{type(data).__name__}. Raw: {raw[:300]!r}"
            )

        results: list[ClassifyBatchItem | None] = [None] * n
        for item_data in data:
            if not isinstance(item_data, dict):
                continue
            try:
                item = ClassifyBatchItem(**item_data)
            except (ValidationError, TypeError):
                continue
            zero_idx = item.idx - 1  # 1-based → 0-based
            if 0 <= zero_idx < n:
                results[zero_idx] = item

        return results

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
