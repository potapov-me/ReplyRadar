"""Integration-тесты LLMClient — реальные запросы к LM Studio.

Запускаются только при живой LM Studio: make test-integration
Пропускаются автоматически если LM Studio недоступна.

Ассерты намеренно консервативны: проверяем что модель правильно классифицирует
очевидные примеры, которые должна решить любая разумная LLM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from replyradar.llm.client import LLMClient

# ── Classify: одиночные запросы ───────────────────────────────────────────────


@pytest.mark.integration
class TestClassifyLive:
    async def test_explicit_commitment_is_signal(self, llm_client: LLMClient) -> None:
        """Явное обязательство с дедлайном — бесспорный сигнал."""
        result = await llm_client.classify("Ок, пришлю отчёт до пятницы", "Иван")

        assert result.is_signal is True, (
            f"Ожидали is_signal=True, получили {result.is_signal} "
            f"(confidence={result.confidence:.2f}, types={result.signal_types})"
        )

    async def test_emoji_reaction_is_noise(self, llm_client: LLMClient) -> None:
        """Emoji-реакция без содержания — бесспорный шум."""
        result = await llm_client.classify("👍", "Боб")

        assert result.is_signal is False, (
            f"Ожидали is_signal=False, получили {result.is_signal} "
            f"(confidence={result.confidence:.2f})"
        )

    async def test_direct_question_is_signal(self, llm_client: LLMClient) -> None:
        """Прямой вопрос, ожидающий ответа — сигнал типа pending_reply."""
        result = await llm_client.classify("Ты не забыл про встречу завтра в 10?", "Лена")

        assert result.is_signal is True

    async def test_smalltalk_is_noise(self, llm_client: LLMClient) -> None:
        """Светская беседа без информационной ценности — шум."""
        result = await llm_client.classify("Спокойной ночи", "Маша")

        assert result.is_signal is False

    async def test_response_matches_contract(self, llm_client: LLMClient) -> None:
        """Ответ LLM десериализуется в валидный ClassifyResponse без исключений."""
        result = await llm_client.classify(
            "Сделаю задачу до конца недели", "Алексей"
        )

        # Если LLMClient не бросил исключение — контракт соблюдён
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.signal_types, list)
        if result.is_signal:
            valid_types = {"commitment", "pending_reply", "communication_risk"}
            assert all(t in valid_types for t in result.signal_types), (
                f"Неизвестные типы: {set(result.signal_types) - valid_types}"
            )
        else:
            assert result.signal_types == []

    async def test_commitment_signal_type_present(self, llm_client: LLMClient) -> None:
        """Явный commitment сопровождается signal_type 'commitment'."""
        result = await llm_client.classify("Перезвоню через полчаса", "Коля")

        assert result.is_signal is True
        assert "commitment" in result.signal_types, (
            f"Ожидали 'commitment' в signal_types, получили {result.signal_types}"
        )


# ── Classify: batch ───────────────────────────────────────────────────────────


@pytest.mark.integration
class TestClassifyBatchLive:
    async def test_batch_returns_correct_count(self, llm_client: LLMClient) -> None:
        """Batch из N сообщений возвращает ровно N результатов."""
        messages = [
            {"id": 1, "text": "Пришлю файл до вечера", "sender_name": "Иван"},
            {"id": 2, "text": "ок", "sender_name": "Маша"},
            {"id": 3, "text": "Когда будет готово?", "sender_name": "Лена"},
        ]
        results = await llm_client.classify_batch(messages)

        assert len(results) == 3

    async def test_batch_obvious_signal_classified(self, llm_client: LLMClient) -> None:
        """Явный commitment в batch классифицируется как сигнал."""
        messages = [
            {"id": 1, "text": "Ок, пришлю отчёт до пятницы", "sender_name": "Иван"},
            {"id": 2, "text": "хаха", "sender_name": "Боб"},
        ]
        results = await llm_client.classify_batch(messages)

        # Первое сообщение — очевидный commitment
        assert results[0] is not None, "LLM пропустила первый элемент батча"
        assert results[0].is_signal is True, (
            f"Ожидали is_signal=True для явного commitment, получили {results[0].is_signal}"
        )

    async def test_batch_obvious_noise_classified(self, llm_client: LLMClient) -> None:
        """Явный шум в batch классифицируется как не-сигнал."""
        messages = [
            {"id": 1, "text": "Ок, пришлю отчёт до пятницы", "sender_name": "Иван"},
            {"id": 2, "text": "хаха", "sender_name": "Боб"},
        ]
        results = await llm_client.classify_batch(messages)

        assert results[1] is not None, "LLM пропустила второй элемент батча"
        assert results[1].is_signal is False, (
            f"Ожидали is_signal=False для реакции, получили {results[1].is_signal}"
        )

    async def test_batch_results_have_valid_confidence(self, llm_client: LLMClient) -> None:
        """Все непустые результаты batch имеют корректный confidence в [0, 1]."""
        messages = [
            {"id": i, "text": text, "sender_name": "Alice"}
            for i, text in enumerate([
                "Сделаю до завтра",
                "ок",
                "Когда встреча?",
            ], start=1)
        ]
        results = await llm_client.classify_batch(messages)

        for i, r in enumerate(results):
            if r is not None:
                assert 0.0 <= r.confidence <= 1.0, (
                    f"Результат [{i}] имеет некорректный confidence={r.confidence}"
                )


# ── Extract ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestExtractLive:
    async def test_commitment_extracted(self, llm_client: LLMClient) -> None:
        """Явное обязательство → хотя бы один commitment в результате."""
        result = await llm_client.extract(
            "Ок, я пришлю тебе файл сегодня вечером", "Иван"
        )

        assert len(result.commitments) >= 1, (
            f"Ожидали ≥1 commitment, получили {len(result.commitments)}"
        )

    async def test_pending_reply_extracted(self, llm_client: LLMClient) -> None:
        """Прямой вопрос → хотя бы один pending_reply."""
        result = await llm_client.extract(
            "Дай знать когда будешь готов к звонку", "Петя"
        )

        assert len(result.pending_replies) >= 1, (
            f"Ожидали ≥1 pending_reply, получили {len(result.pending_replies)}"
        )

    async def test_risk_extracted(self, llm_client: LLMClient) -> None:
        """Явный конфликт → хотя бы один communication_risk."""
        result = await llm_client.extract(
            "Ты обещал прислать данные ещё вчера, а я до сих пор ничего не получил",
            "Сергей",
        )

        assert len(result.communication_risks) >= 1 or len(result.pending_replies) >= 1, (
            "Ожидали risk или pending_reply для нарушенного дедлайна"
        )

    async def test_extract_response_matches_contract(self, llm_client: LLMClient) -> None:
        """Ответ LLM десериализуется без исключений для произвольного signal-сообщения."""
        result = await llm_client.extract(
            "Скинь мне ссылку на репозиторий пожалуйста", "Катя"
        )

        # Если не бросило исключение — контракт соблюдён
        assert isinstance(result.commitments, list)
        assert isinstance(result.pending_replies, list)
        assert isinstance(result.communication_risks, list)
        # urgency в pending_replies должен быть одним из допустимых значений
        for pr in result.pending_replies:
            assert pr.urgency in {"high", "medium", "low"}, (
                f"Некорректный urgency: {pr.urgency!r}"
            )
