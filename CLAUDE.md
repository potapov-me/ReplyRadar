# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Установить зависимости
uv sync

# Запустить API
uvicorn src.replyradar.main:app --reload

# Запустить дайджест (CLI)
python -m replyradar digest

# Создать миграцию Alembic
alembic revision --autogenerate -m "описание"

# Применить миграции
alembic upgrade head
```

## Архитектура

ReplyRadar — single-user, local-first инструмент навигации по Telegram-перепискам. Работает как **единый asyncio-процесс** (ADR-0003): listener, processing engine, API и scheduler в одном event loop.

### Поток данных

```
Telegram (Telethon) → messages (raw, immutable) → Processing Engine → Postgres + pgvector
                                                                              ↓
                                                              FastAPI (use-case API) / Digest CLI → Telegram Bot
```

### Processing Engine

Четыре независимые стадии на каждое сообщение:

| Стадия | Флаг завершения | Условие запуска |
|--------|-----------------|-----------------|
| Classify | `classified_at` | всегда |
| Extract | `extracted_at` | `is_signal = true` |
| Embed | `embedded_at` | после classify |
| EntityExtract | `entities_extracted_at` | все сообщения, батчами |

Каждая стадия идемпотентна: пишет timestamp при успехе, пишет `*_error` при сбое и оставляет timestamp NULL для retry при следующем запуске. Частичный успех не откатывается.

Два источника задач: realtime (`asyncio.Queue` от listener) и backfill (`WHERE classified_at IS NULL ORDER BY timestamp ASC`). Realtime имеет приоритет над backfill.

EntityExtract запускается батчами (один LLM-вызов на батч), не per-message. Backfill: `WHERE entities_extracted_at IS NULL`.

### LLM

Все вызовы LLM идут локально через **LM Studio** (OpenAI-совместимый API). **LiteLLM** — единый клиентский интерфейс.

```yaml
# Конфигурация LLM
llm:
  base_url: http://host.docker.internal:1234/v1
  model: local-model
  api_key: lm-studio

embedding:
  provider: lmstudio
  model: text-embedding-nomic-embed-text-v1.5
  base_url: http://host.docker.internal:1234/v1
```

При недоступности LM Studio — сообщения остаются в ingestion, обработка откладывается, все timestamps остаются NULL. Обработка продолжится автоматически при следующем запуске.

### Ключевые инварианты

- **Postgres — единственный источник истины.** Очередь — только транспорт.
- **Тексты сообщений не попадают в stdout-логи.** Только ID, метрики, статусы.
- **`mark_read()` и `send_read_acknowledge()` нигде не вызываются** — ReplyRadar не меняет статус прочтения в Telegram.
- Дубли при пересечении backfill и realtime stream: `INSERT ... ON CONFLICT (chat_id, telegram_msg_id) DO NOTHING`.
- Удаление чата (`DELETE /chats/{id}`) удаляет все данные каскадно, включая embeddings и superseded записи.

### Entity Knowledge Graph

Отдельная подсистема — база знаний о людях и организациях, упомянутых в переписках. Не смешивается с дайджестом, дайджест может ссылаться на сущности по имени + ID.

- `entities` — люди и организации в единой таблице (`entity_type: person|organization`). Организации — полноправные узлы для транзитивных цепочек.
- `entity_facts` — атрибуты сущности (роль, место работы, черта)
- `entity_relations` — рёбра между сущностями (works_with, dating, reports_to, …)
- `entity_fact_sources` / `entity_relation_sources` — источники для честного подсчёта corroboration

Транзитивные запросы через рекурсивный CTE по `entity_relations`. Уверенность перемножается по цепочке.

Каждый факт/связь имеет `base_confidence` (от LLM), `source_type` (self/other/inferred), `corroboration_count`, `contradiction_count`, `first_seen_at`, `last_confirmed_at`. Финальный score вычисляется при запросе с учётом затухания по времени (период полураспада 1 год).

### API (FastAPI)

```
GET  /today                      # pending replies urgency=high + open commitments + active risks
GET  /pending                    # pending replies
GET  /commitments                # open commitments
GET  /risks                      # active communication risks
GET  /chats/{id}/summary
POST /chats/{id}/monitor
POST /backfill
GET  /backfill/status
POST /chats/{id}/summarize
GET  /status
DELETE /chats/{id}

# Entity Knowledge Graph
GET  /people                     # список людей
GET  /people/{id}                # профиль: факты + прямые связи
GET  /people/{id}/connections    # транзитивный граф до N хопов
GET  /people/{id}/timeline       # факты хронологически
GET  /people/{id}/messages       # сообщения-источники фактов
GET  /people/search?q=
POST /people/{a}/merge/{b}       # ручная склейка
POST /people/{a}/relate/{b}      # ручная связь
GET  /orgs/{id}                  # профиль организации
```

### Summarizer

Обновляется по расписанию раз в час (APScheduler) или по запросу `POST /chats/{id}/summarize`.

### Документация

- [Архитектура](./docs/architecture.md) — детальное описание всех компонентов и схемы БД
- [Файловая структура](./docs/structure.md) — организация кодовой базы и ключевые принципы
- [Глоссарий](./docs/glossary.md) — ubiquitous language: термины домена
- [План разработки](./docs/plan.md) — этапы с артефактами
- [ADR](./docs/adr/README.md) — архитектурные решения (local-first, Postgres, single-process, local LLM, use-case API, entity graph, confidence scoring, asyncpg, tactical DDD, quarantine, audit trail, CQRS-lite, policy-as-code)
