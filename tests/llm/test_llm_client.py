"""Тесты LLMClient: classify(), classify_batch(), _parse_batch_classify().

Стратегия: litellm.acompletion заменяется AsyncMock — тестируем контракт
клиента (промпт-строки, max_tokens, обработку ошибок, парсинг JSON),
не взаимодействуя с реальной LM Studio.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from replyradar.config import EmbeddingConfig, LLMConfig
from replyradar.llm.client import (
    LLMClient,
    LLMUnavailableError,
    PermanentLLMError,
    TransientLLMError,
)
from replyradar.llm.contracts.classify import ClassifyBatchItem


# ── helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> LLMClient:
    return LLMClient(
        LLMConfig(base_url="http://test", model="test-model", api_key="test"),
        EmbeddingConfig(base_url="http://test", model="test-emb"),
    )


def _resp(content: str) -> MagicMock:
    """Mock litellm response с заданным текстом ответа."""
    r = MagicMock()
    r.choices = [MagicMock()]
    r.choices[0].message.content = content
    r.usage.prompt_tokens = 10
    r.usage.completion_tokens = 5
    return r


def _batch_json(*items: dict) -> str:
    return json.dumps(list(items))


# ── _parse_batch_classify (static, без I/O) ───────────────────────────────────


class TestParseBatchClassify:
    def test_all_items_present(self) -> None:
        raw = _batch_json(
            {"idx": 1, "is_signal": True, "confidence": 0.9, "signal_types": ["commitment"]},
            {"idx": 2, "is_signal": False, "confidence": 0.95, "signal_types": []},
            {"idx": 3, "is_signal": True, "confidence": 0.8, "signal_types": ["pending_reply"]},
        )
        results = LLMClient._parse_batch_classify(raw, 3)

        assert len(results) == 3
        assert results[0] is not None and results[0].is_signal is True
        assert results[1] is not None and results[1].is_signal is False
        assert results[2] is not None and results[2].signal_types == ["pending_reply"]

    def test_missing_idx_returns_none(self) -> None:
        # idx=2 пропущен — element at position 1 должен быть None
        raw = _batch_json(
            {"idx": 1, "is_signal": False, "confidence": 0.9, "signal_types": []},
            {"idx": 3, "is_signal": True, "confidence": 0.7, "signal_types": ["commitment"]},
        )
        results = LLMClient._parse_batch_classify(raw, 3)

        assert results[0] is not None
        assert results[1] is None  # idx=2 отсутствует
        assert results[2] is not None

    def test_strips_markdown_fences(self) -> None:
        inner = _batch_json(
            {"idx": 1, "is_signal": False, "confidence": 0.9, "signal_types": []}
        )
        raw = f"```json\n{inner}\n```"
        results = LLMClient._parse_batch_classify(raw, 1)

        assert results[0] is not None and results[0].is_signal is False

    def test_non_array_raises_permanent(self) -> None:
        raw = json.dumps({"idx": 1, "is_signal": True, "confidence": 0.9, "signal_types": []})
        with pytest.raises(PermanentLLMError, match="ожидался массив"):
            LLMClient._parse_batch_classify(raw, 1)

    def test_invalid_json_raises_permanent(self) -> None:
        with pytest.raises(PermanentLLMError, match="разобрать JSON"):
            LLMClient._parse_batch_classify("не JSON", 2)

    def test_idx_out_of_range_ignored(self) -> None:
        raw = _batch_json({"idx": 99, "is_signal": True, "confidence": 0.9, "signal_types": []})
        results = LLMClient._parse_batch_classify(raw, 2)

        assert results[0] is None
        assert results[1] is None

    def test_invalid_item_skipped_rest_parsed(self) -> None:
        # Первый элемент нарушает контракт (нет is_signal), второй — валидный
        raw = _batch_json(
            {"idx": 1, "confidence": 0.9},  # нет is_signal → Pydantic отклонит
            {"idx": 2, "is_signal": False, "confidence": 0.8, "signal_types": []},
        )
        results = LLMClient._parse_batch_classify(raw, 2)

        assert results[0] is None   # пропущен из-за ошибки контракта
        assert results[1] is not None and results[1].is_signal is False

    def test_empty_array_returns_all_none(self) -> None:
        results = LLMClient._parse_batch_classify("[]", 3)
        assert results == [None, None, None]


# ── classify() ────────────────────────────────────────────────────────────────


class TestClassify:
    async def test_returns_signal(self, client: LLMClient) -> None:
        payload = '{"is_signal": true, "confidence": 0.9, "signal_types": ["commitment"]}'
        with patch("litellm.acompletion", AsyncMock(return_value=_resp(payload))):
            result = await client.classify("пришли отчёт до пятницы", "Alice")

        assert result.is_signal is True
        assert result.signal_types == ["commitment"]
        assert result.confidence == pytest.approx(0.9)

    async def test_returns_noise(self, client: LLMClient) -> None:
        payload = '{"is_signal": false, "confidence": 0.95, "signal_types": []}'
        with patch("litellm.acompletion", AsyncMock(return_value=_resp(payload))):
            result = await client.classify("ок", "Bob")

        assert result.is_signal is False
        assert result.signal_types == []

    async def test_passes_max_tokens_100(self, client: LLMClient) -> None:
        """classify() должен передавать max_tokens=100 — ответ компактный (~40 токенов)."""
        payload = '{"is_signal": false, "confidence": 0.9, "signal_types": []}'
        mock = AsyncMock(return_value=_resp(payload))
        with patch("litellm.acompletion", mock):
            await client.classify("текст", "Alice")

        assert mock.call_args.kwargs.get("max_tokens") == 100

    async def test_strips_markdown_fences(self, client: LLMClient) -> None:
        inner = '{"is_signal": true, "confidence": 0.7, "signal_types": ["pending_reply"]}'
        payload = f"```json\n{inner}\n```"
        with patch("litellm.acompletion", AsyncMock(return_value=_resp(payload))):
            result = await client.classify("ты не ответил", "Alice")

        assert result.is_signal is True

    async def test_invalid_json_raises_permanent(self, client: LLMClient) -> None:
        with patch("litellm.acompletion", AsyncMock(return_value=_resp("не JSON"))):
            with pytest.raises(PermanentLLMError):
                await client.classify("текст", "Alice")

    async def test_schema_violation_raises_permanent(self, client: LLMClient) -> None:
        # is_signal отсутствует — нарушение Pydantic-контракта
        with patch("litellm.acompletion", AsyncMock(return_value=_resp('{"confidence": 0.5}'))):
            with pytest.raises(PermanentLLMError):
                await client.classify("текст", "Alice")

    async def test_transient_exception_raises_unavailable(self, client: LLMClient) -> None:
        """Любое исключение из _TRANSIENT_EXCEPTIONS → LLMUnavailableError."""
        with patch("replyradar.llm.client._TRANSIENT_EXCEPTIONS", (RuntimeError,)):
            with patch("litellm.acompletion", AsyncMock(side_effect=RuntimeError("timeout"))):
                with pytest.raises(LLMUnavailableError):
                    await client.classify("текст", "Alice")

    async def test_no_models_loaded_raises_unavailable(self, client: LLMClient) -> None:
        """LM Studio специфика: 'No models loaded' → LLMUnavailableError."""
        with patch("litellm.acompletion", AsyncMock(side_effect=Exception("No models loaded"))):
            with pytest.raises(LLMUnavailableError):
                await client.classify("текст", "Alice")


# ── classify_batch() ──────────────────────────────────────────────────────────


class TestClassifyBatch:
    _MSGS = [
        {"id": 1, "text": "пришли отчёт", "sender_name": "Alice"},
        {"id": 2, "text": "ок", "sender_name": "Bob"},
        {"id": 3, "text": "ты не ответил на вопрос", "sender_name": "Alice"},
    ]

    async def test_returns_all_results_in_order(self, client: LLMClient) -> None:
        payload = _batch_json(
            {"idx": 1, "is_signal": True, "confidence": 0.9, "signal_types": ["commitment"]},
            {"idx": 2, "is_signal": False, "confidence": 0.95, "signal_types": []},
            {"idx": 3, "is_signal": True, "confidence": 0.8, "signal_types": ["pending_reply"]},
        )
        with patch("litellm.acompletion", AsyncMock(return_value=_resp(payload))):
            results = await client.classify_batch(self._MSGS)

        assert len(results) == 3
        assert results[0] is not None and results[0].is_signal is True
        assert results[1] is not None and results[1].is_signal is False
        assert results[2] is not None and results[2].is_signal is True

    async def test_partial_miss_returns_none_for_missing(self, client: LLMClient) -> None:
        # idx=2 пропущен — позиция 1 должна быть None
        payload = _batch_json(
            {"idx": 1, "is_signal": True, "confidence": 0.9, "signal_types": ["commitment"]},
            {"idx": 3, "is_signal": False, "confidence": 0.9, "signal_types": []},
        )
        with patch("litellm.acompletion", AsyncMock(return_value=_resp(payload))):
            results = await client.classify_batch(self._MSGS)

        assert results[0] is not None
        assert results[1] is None
        assert results[2] is not None

    async def test_max_tokens_equals_n_times_60_plus_30(self, client: LLMClient) -> None:
        """max_tokens масштабируется по размеру батча."""
        n = len(self._MSGS)
        payload = _batch_json(*[
            {"idx": i + 1, "is_signal": False, "confidence": 0.9, "signal_types": []}
            for i in range(n)
        ])
        mock = AsyncMock(return_value=_resp(payload))
        with patch("litellm.acompletion", mock):
            await client.classify_batch(self._MSGS)

        assert mock.call_args.kwargs.get("max_tokens") == n * 60 + 30

    async def test_total_json_failure_raises_permanent(self, client: LLMClient) -> None:
        with patch("litellm.acompletion", AsyncMock(return_value=_resp("не JSON"))):
            with pytest.raises(PermanentLLMError):
                await client.classify_batch(self._MSGS)

    async def test_non_array_response_raises_permanent(self, client: LLMClient) -> None:
        payload = '{"idx": 1, "is_signal": true, "confidence": 0.9, "signal_types": []}'
        with patch("litellm.acompletion", AsyncMock(return_value=_resp(payload))):
            with pytest.raises(PermanentLLMError, match="ожидался массив"):
                await client.classify_batch(self._MSGS)

    async def test_unavailable_propagates(self, client: LLMClient) -> None:
        with patch("replyradar.llm.client._TRANSIENT_EXCEPTIONS", (RuntimeError,)):
            with patch("litellm.acompletion", AsyncMock(side_effect=RuntimeError("conn refused"))):
                with pytest.raises(LLMUnavailableError):
                    await client.classify_batch(self._MSGS)

    async def test_newlines_in_message_text_are_collapsed(self, client: LLMClient) -> None:
        """Переносы строк в тексте сообщения схлопываются: не ломают inline-формат промпта."""
        messages = [{"id": 1, "text": "строка 1\nстрока 2\nстрока 3", "sender_name": "Alice"}]
        payload = _batch_json({"idx": 1, "is_signal": False, "confidence": 0.9, "signal_types": []})
        mock = AsyncMock(return_value=_resp(payload))
        with patch("litellm.acompletion", mock):
            await client.classify_batch(messages)

        user_content: str = mock.call_args.kwargs["messages"][1]["content"]
        # Переносы строк из текста сообщения не должны попасть в промпт как сырые \n
        assert "строка 1\n" not in user_content
        assert "строка 1 строка 2 строка 3" in user_content
