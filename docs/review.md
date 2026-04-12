# Code Review: этап 4

## Статус

Все находки этапа 4 исправлены. Ниже — архивная запись того, что было найдено и как исправлено.

---

## Findings и исправления

### High

**1. `status.py` — 4 COUNT(*) с коррелированными NOT EXISTS + outbound TCP на каждый `/status`**

Два запроса к `backlog_classify` и `backlog_extract` делали коррелированный подзапрос `NOT EXISTS` без покрывающего индекса. Сверху — синхронный `check_health()` к LM Studio без кеша.

*Исправление:* два `COUNT(*) FILTER` объединены в один `FROM messages` через `fetchrow`. Добавлен TTL-кеш 10 с для `check_health()` через `app.state._llm_health_cache`. Миграция `0002` создаёт `CREATE INDEX ix_processing_quarantine_active ON processing_quarantine (message_id, stage) WHERE reviewed_at IS NULL`.

**2. `backfill.py` — последовательный `msg.get_sender()` на каждое сообщение в батче**

`_flush_buffer` делал отдельный Telegram RPC на каждое сообщение. При батче из 20 — 20 последовательных вызовов. Для чата с 50 000 сообщений backfill занимал часы.

*Исправление:* добавлен `sender_cache: dict[int, str | None]` внутри `_flush_buffer`. Для большинства батчей (один-два отправителя) теперь 1–2 `get_sender()` вместо N.

### Medium

**3. `extract.py` — N sequential INSERT на каждое is_signal сообщение**

Три цикла `await upsert_commitment / upsert_pending_reply / upsert_communication_risk` выполнялись поштучно.

*Исправление:* добавлен `upsert_signals_batch()` в `signals.py` — один `executemany` на таблицу. `extract.py` переведён на batch-вызов.

**4. `engine.py:120` — busy-wait spinloop пока queue непуста**

`await asyncio.sleep(0.1)` в цикле при непустой очереди.

*Исправление:* заменено на `await self._queue.join()` — backfill корректно ждёт опустошения realtime-очереди через механизм asyncio, не опрашивая её каждые 100 мс.

**5. `engine.py:183` + `status.py` — NOT EXISTS без индекса**

Каждый backfill-проход и каждый `/status` делали `NOT EXISTS (SELECT 1 FROM processing_quarantine ...)` без покрывающего индекса.

*Исправление:* миграция `0002_quarantine_index.py` — partial index на `(message_id, stage) WHERE reviewed_at IS NULL`.

**6. `client.py:228-298` — дублирование блоков обработки ошибок**

Идентичный паттерн `except _TRANSIENT_EXCEPTIONS / except Exception` скопирован в `embed()` и `_complete()`.

*Исправление:* выделен `_raise_llm_error(exc, stage, msg_id, t0) -> NoReturn`. Оба метода схлопнуты до одного `except Exception as exc: _raise_llm_error(...)`.

### Low

**7. `classify.py:102` — `strict=False` в `zip(need_llm, results)`**

При нарушении контракта `classify_batch` молча отбрасывал хвост.

*Исправление:* `strict=True`.

**8. `client.py:340` — PEP 695 generic syntax `_parse[T]`**

*Исправление:* `_T = TypeVar("_T")` на уровне модуля, `def _parse(model: type[_T], ...)`.

**9. `embed.py:68` — `str(v)` для float**

*Исправление:* `repr(v)`.

---

## Coverage gaps (не закрыты)

- Нет тестов для `run_extract` — корректность batch-upsert и `upsert_signals_batch` не покрыты.
- Нет тестов для `engine._run_stage` с retry/quarantine-логикой.
- Нет тестов для `backfill._flush_buffer` — sender-кеш и сохранение батча.
- Нет тестов для `/status` endpoint.

## Assumptions

- Ревью выполнено по ветке `main` после всех исправлений
- Полноценный e2e прогон с живыми Postgres, LM Studio и Telegram не выполнялся

## Checks

- `uv run pytest -q .` — 65 passed, 14 skipped
- `python3 -m compileall src tests` — ok

## Residual Risks

- Batch-classify в backfill намеренно работает без `context_window` (`engine.py:124-130`). Поведенческая регрессия для коротких реплик («ок, сделаю»). Fallback через `_classify_one_fallback` частично компенсирует только для элементов, пропущенных LLM. Realtime-путь всегда получает контекст.
- Retry-счётчики в памяти (`engine.py:13`). Документировано как MVP-решение.
- Нет e2e-теста, подтверждающего полный путь backfill/realtime → `commitments`, `pending_replies`, `communication_risks`.
