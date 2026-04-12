# План разработки

Документ разделяет уже завершённые этапы и следующие очереди работы. Он должен совпадать с текущим кодом, а не с полной целевой архитектурой.

## Уже сделано

### Этап 1. Фундамент

Сделано:

- `src`-layout и базовая упаковка проекта
- `config.py` + `config/default.yaml`
- логирование
- пул БД и Alembic
- `GET /status`
- тест на import boundaries

### Этап 2. Ingestion

Сделано:

- `TelegramListener`
- `POST /chats/{id}/monitor`
- `BackfillRunner`
- `POST /backfill`
- `GET /backfill/status`

### Этап 2.5. Telegram Desktop import

Сделано:

- `tg_export_parser.py`
- `POST /import/telegram-export`
- импорт single-chat и account export форматов
- идемпотентная загрузка сообщений

### Этап 3. Processing core

Сделано:

- `LLMClient`
- стадии `classify`, `extract`, `embed`
- `ProcessingEngine`
- quarantine-обработка
- `GET /admin/quarantine`
- `POST /admin/quarantine/{id}/reprocess|skip`
- offline evals для `classify` и `extract`

Code review (этап 4):

- batch classify (`run_classify_batch`) + fallback на per-message с восстановлением контекста
- `upsert_signals_batch` — batch upsert commitments/pending_replies/risks одним `executemany`
- backfill: sender-кеш по `sender_id` внутри батча
- `queue.join()` вместо spinloop в backfill-loop
- partial index `ix_processing_quarantine_active` (migration 0002)
- TTL-кеш для `check_health()` в `/status`
- объединение двух COUNT-запросов в один scan в `/status`
- выделен `_raise_llm_error` в `LLMClient`

## В работе / следующий приоритет

### Этап 4. Scenario API

Нужно добавить read-model и пользовательские ручки:

- `/today`
- `/pending`
- `/commitments`
- `/risks`

Зависимости:

- стабильные запросы к сигналам
- понятная агрегация поверх `commitments`, `pending_replies`, `communication_risks`

### Этап 5. Knowledge graph

Нужно добавить:

- извлечение сущностей
- таблицы для `entities`, `facts`, `relations`
- resolution / activation
- query API `/people`, `/orgs`

Сейчас в репозитории есть ADR и config-параметры под этот слой, но runtime-реализации ещё нет.

## После этого

### Этап 6. Summarizer / Digest

План:

- per-chat summary
- CLI / bot delivery digest
- graceful degradation при недоступной LLM

### Этап 7. Scheduler и расширенная observability

План:

- планировщик фоновых задач
- дополнительные операционные метрики
- runbooks под типовые сбои

## Отдельный долг

### Durable ingest buffer

Самый заметный технический долг текущей архитектуры: при недоступной БД realtime-ingestion не буферизуется на диск.

После стабилизации основных API логичный следующий шаг:

- локальный durable buffer между Telethon и Postgres
- безопасный replay после рестарта БД
