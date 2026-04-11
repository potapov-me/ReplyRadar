"""Fixtures для integration-тестов с живой LM Studio.

Проверка доступности выполняется ОДИН РАЗ на сессию через отдельный event loop —
не занимает время pytest-asyncio и не конфликтует с его event loop.
Все тесты в модуле пропускаются если LM Studio недоступна.
"""

from __future__ import annotations

import asyncio

import pytest

from replyradar.config import get_settings
from replyradar.llm.client import LLMClient


@pytest.fixture(scope="session")
def _llm_available() -> bool:
    """Возвращает True если LM Studio отвечает на health-check."""
    settings = get_settings()
    client = LLMClient(settings.llm, settings.embedding)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(client.check_health())
    finally:
        loop.close()


@pytest.fixture
async def llm_client(_llm_available: bool) -> LLMClient:
    """Возвращает LLMClient или пропускает тест если LM Studio недоступна."""
    if not _llm_available:
        pytest.skip("LM Studio недоступна — запустите и загрузите модель для integration-тестов")
    settings = get_settings()
    return LLMClient(settings.llm, settings.embedding)
