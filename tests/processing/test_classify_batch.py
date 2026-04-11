"""Тесты run_classify_batch(): batch-путь classify + fallback-логика.

Мокаем LLMClient и asyncpg.Pool — тестируем координацию, обработку ошибок,
идемпотентность БД-вызовов без реального LLM и Postgres.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from replyradar.llm.client import LLMUnavailableError, PermanentLLMError, TransientLLMError
from replyradar.llm.contracts.classify import ClassifyBatchItem
from replyradar.processing.classify import run_classify_batch


# ── helpers ──────────────────────────────��────────────────────────────────��───


def _item(idx: int, is_signal: bool) -> ClassifyBatchItem:
    return ClassifyBatchItem(
        idx=idx,
        is_signal=is_signal,
        confidence=0.9,
        signal_types=["commitment"] if is_signal else [],
    )


@pytest.fixture
def pool() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def llm() -> MagicMock:
    m = MagicMock()
    m.classify_batch = AsyncMock()
    return m


# ── тесты ────────────────────────────���─────────────────────────────────���──────


class TestRunClassifyBatch:
    async def test_empty_messages_returns_empty(self, pool: AsyncMock, llm: MagicMock) -> None:
        failed = await run_classify_batch(pool, messages=[], llm=llm)

        assert failed == []
        llm.classify_batch.assert_not_called()
        pool.execute.assert_not_called()

    async def test_no_text_marked_as_not_signal_without_llm(
        self, pool: AsyncMock, llm: MagicMock
    ) -> None:
        """Сообщения без текста помечаются is_signal=False без LLM-вызова."""
        messages = [
            {"id": 1, "text": None, "sender_name": "Alice", "chat_id": 10},
            {"id": 2, "text": "", "sender_name": "Bob", "chat_id": 10},
        ]
        failed = await run_classify_batch(pool, messages=messages, llm=llm)

        assert failed == []
        llm.classify_batch.assert_not_called()
        assert pool.execute.call_count == 2
        # Оба — is_signal=False
        for c in pool.execute.call_args_list:
            assert c.args[1] is False  # $1 = is_signal

    async def test_happy_path_all_classified(self, pool: AsyncMock, llm: MagicMock) -> None:
        messages = [
            {"id": 10, "text": "пришли отчёт", "sender_name": "Alice", "chat_id": 1},
            {"id": 11, "text": "ок, сделаю", "sender_name": "Bob", "chat_id": 1},
        ]
        llm.classify_batch = AsyncMock(return_value=[_item(1, True), _item(2, False)])

        failed = await run_classify_batch(pool, messages=messages, llm=llm)

        assert failed == []
        assert pool.execute.call_count == 2
        # Порядок и is_signal проверяем по позиционным аргументам pool.execute
        calls = pool.execute.call_args_list
        assert calls[0].args[1] is True   # msg_id=10 → is_signal=True
        assert calls[0].args[3] == 10     # message_id
        assert calls[1].args[1] is False  # msg_id=11 → is_signal=False
        assert calls[1].args[3] == 11

    async def test_partial_miss_returns_failed_ids(
        self, pool: AsyncMock, llm: MagicMock
    ) -> None:
        """Элементы, пропущенные LLM, возвращаются как failed_ids для fallback."""
        messages = [
            {"id": 20, "text": "текст 1", "sender_name": "A", "chat_id": 1},
            {"id": 21, "text": "текст 2", "sender_name": "B", "chat_id": 1},  # ← пропустит LLM
            {"id": 22, "text": "текст 3", "sender_name": "C", "chat_id": 1},
        ]
        # Позиция 1 (msg_id=21) — None: LLM не вернул результат
        llm.classify_batch = AsyncMock(return_value=[_item(1, False), None, _item(3, True)])

        failed = await run_classify_batch(pool, messages=messages, llm=llm)

        assert failed == [21]
        assert pool.execute.call_count == 2  # только 20 и 22 помечены

    async def test_permanent_error_returns_all_failed(
        self, pool: AsyncMock, llm: MagicMock
    ) -> None:
        """PermanentLLMError (плохой ответ модели) → все ID уходят в fallback."""
        messages = [
            {"id": 30, "text": "текст", "sender_name": "A", "chat_id": 1},
            {"id": 31, "text": "текст", "sender_name": "B", "chat_id": 1},
        ]
        llm.classify_batch = AsyncMock(side_effect=PermanentLLMError("bad JSON response"))

        failed = await run_classify_batch(pool, messages=messages, llm=llm)

        assert set(failed) == {30, 31}
        pool.execute.assert_not_called()

    async def test_transient_error_returns_all_failed(
        self, pool: AsyncMock, llm: MagicMock
    ) -> None:
        """TransientLLMError (rate limit, timeout) не должен крашить backfill-воркер.

        Регрессионный тест: до исправления TransientLLMError пробрасывался голым
        из run_classify_batch и роняла таск engine:backfill вместо fallback.
        """
        messages = [
            {"id": 40, "text": "текст", "sender_name": "A", "chat_id": 1},
            {"id": 41, "text": "текст", "sender_name": "B", "chat_id": 1},
        ]
        llm.classify_batch = AsyncMock(side_effect=TransientLLMError("rate limit 429"))

        failed = await run_classify_batch(pool, messages=messages, llm=llm)

        assert set(failed) == {40, 41}
        pool.execute.assert_not_called()

    async def test_unavailable_error_propagates(
        self, pool: AsyncMock, llm: MagicMock
    ) -> None:
        """LLMUnavailableError пробрасывается: engine должен ждать восстановления LM Studio."""
        messages = [{"id": 50, "text": "текст", "sender_name": "A", "chat_id": 1}]
        llm.classify_batch = AsyncMock(side_effect=LLMUnavailableError("LM Studio not running"))

        with pytest.raises(LLMUnavailableError):
            await run_classify_batch(pool, messages=messages, llm=llm)

        pool.execute.assert_not_called()

    async def test_mixed_text_and_no_text(self, pool: AsyncMock, llm: MagicMock) -> None:
        """Сообщения без текста помечаются сразу; текстовые — через classify_batch."""
        messages = [
            {"id": 60, "text": None, "sender_name": "A", "chat_id": 1},   # → без LLM
            {"id": 61, "text": "жду ответа", "sender_name": "B", "chat_id": 1},  # → LLM
        ]
        llm.classify_batch = AsyncMock(return_value=[_item(1, True)])

        failed = await run_classify_batch(pool, messages=messages, llm=llm)

        assert failed == []
        # classify_batch вызван только с текстовым сообщением
        [batch_arg] = llm.classify_batch.call_args.args
        assert len(batch_arg) == 1
        assert batch_arg[0]["id"] == 61
        # pool.execute вызван дважды: no-text (id=60) + classified (id=61)
        assert pool.execute.call_count == 2

    async def test_all_no_text_skips_llm_entirely(
        self, pool: AsyncMock, llm: MagicMock
    ) -> None:
        messages = [
            {"id": 70, "text": None, "sender_name": "A", "chat_id": 1},
            {"id": 71, "text": None, "sender_name": "B", "chat_id": 1},
        ]
        failed = await run_classify_batch(pool, messages=messages, llm=llm)

        assert failed == []
        llm.classify_batch.assert_not_called()
        assert pool.execute.call_count == 2
