# План разработки

Каждый этап завершается рабочим артефактом, который можно потрогать руками. Следующий этап начинается только после того, как артефакт предыдущего работает.

---

## Этап 1. Фундамент

**Что строится:**
- `src`-layout, `pyproject.toml` с зависимостями
- `config.py` — pydantic-settings, читает `config/default.yaml` с policy-as-code значениями (ADR-0014)
- `db/pool.py` — asyncpg connection pool
- `bootstrap.py` — composition root
- Alembic: первая миграция с полной схемой БД (все таблицы из `architecture.md`)
- Архитектурные тесты на import boundaries: `tests/test_import_boundaries.py` запрещает `processing→usecases`, `routes→repos`, `knowledge→api`

**Артефакт:** `uvicorn src.replyradar.main:app` стартует, `GET /status` возвращает component-level состояние. Схема развёрнута. Тест границ импортов проходит в CI.

---

## Этап 2. Ingestion

**Что строится:**
- `ingestion/listener.py` — Telethon listener: подключение, авторизация, realtime поток новых сообщений → `asyncio.Queue`
- `ingestion/backfill.py` — `iter_messages` от старых к новым, батчами
- `db/repos/messages.py` — `INSERT ... ON CONFLICT (chat_id, telegram_msg_id) DO NOTHING`
- `api/routes/chats.py` — `POST /chats/{id}/monitor`, `POST /backfill`, `GET /backfill/status`

**Артефакт:** после `POST /chats/{id}/monitor` и `POST /backfill` сообщения выбранного чата появляются в таблице `messages`. Realtime: новые сообщения попадают в БД без перезапуска. Дубли не создаются.

---

## Этап 3. Processing Core

**Что строится:**
- `llm/client.py` — LiteLLM wrapper; `llm/contracts/` — Pydantic-схемы ответов; `llm/prompts/` — шаблоны
- `processing/classify.py`, `extract.py`, `embed.py` — стадии с таксономией ошибок (transient/permanent/degraded)
- `processing/engine.py` — оркестратор: realtime queue + backfill loop, приоритет realtime
- `db/repos/signals.py` — upsert по `source_fingerprint`
- `db/repos/quarantine.py` — после `MAX_RETRIES` permanent-ошибок сообщение уходит в `processing_quarantine`
- `api/routes/admin.py` — `GET /admin/quarantine`, `POST /admin/quarantine/{id}/reprocess|skip`

**Артефакт:** после backfill таблицы `commitments`, `pending_replies`, `communication_risks` заполнены. Сообщение с невалидным LLM-ответом после N попыток попадает в quarantine, а не зацикливается. `GET /admin/quarantine` показывает список.

---

## Этап 4. API сценариев

**Что строится:**
- `api/routes/chats.py` — `GET /today`, `GET /pending`, `GET /commitments`, `GET /risks`, `GET /chats/{id}/summary`
- `api/deps.py` — зависимости FastAPI: db connection, pagination
- `db/repos/signals.py` — запросы для use-case эндпоинтов

**Артефакт:** `GET /today` возвращает pending replies с `urgency=high`, open commitments с наступившим сроком и active risks — всё в одном ответе. API покрывает все сценарии из `cjm.md` (1–4).

---

## Этап 5. Entity Knowledge Graph — извлечение

**Что строится:**
- `processing/entity_extract.py` — батчевый LLM-вызов; результат — список сущностей, фактов и связей
- `knowledge/activation.py` — activation policy; `knowledge/resolution.py` — merge rules; `knowledge/superseding.py` — contradiction semantics
- `db/repos/entities.py` — upsert с `mention_count`, проверка activation criteria
- `db/repos/audit.py` — запись в `entity_audit_log` при каждой ручной операции
- Optimistic locking: `version` check при activate/mute/merge (ADR-0012)
- Evals: первый golden dataset в `evals/datasets/` для entity extraction
- Backfill entity extraction: `WHERE entities_extracted_at IS NULL`

**Артефакт:** граф заполнен. Candidate/active разделены. Ручной merge записывается в audit log с `payload.before/after`. Повторный merge той же пары возвращает 409 при несовпадении `version`. Evals прогоняются и baseline зафиксирован.

---

## Этап 6. Knowledge API

**Что строится:**
- `knowledge/confidence.py` — `effective_confidence()`: затухание по времени, вес источника, corroboration, contradiction
- `knowledge/graph.py` — рекурсивные CTE для транзитивных запросов, перемножение уверенности по цепочке
- `api/routes/people.py` — `GET /people`, `GET /people/{id}`, `GET /people/{id}/connections`, `GET /people/{id}/timeline`, `GET /people/{id}/messages`, `GET /people/search`
- `api/routes/people.py` — `POST /people/{a}/merge/{b}`, `POST /people/{a}/relate/{b}`
- `api/routes/orgs.py` — `GET /orgs/{id}`

**Артефакт:** `GET /people/{id}/connections?depth=3` возвращает транзитивный граф связей с уверенностью на каждом ребре. Сценарий 5 из `cjm.md` работает end-to-end.

---

## Этап 7. Summarizer и Digest

**Что строится:**
- `summarizer/summarizer.py` — per-chat summary через LLM; пишет в `chat_summaries`; при недоступности LM Studio пропускает без ошибки
- `api/routes/chats.py` — `POST /chats/{id}/summarize`
- `digest/generator.py` — строит текст дайджеста из read-model (commitments + pending_replies + risks + summaries)
- `digest/bot.py` — доставка в Telegram Bot
- CLI: `python -m replyradar digest`

**Артефакт:** `python -m replyradar digest` отправляет сообщение в Telegram с компактным дайджестом. При недоступности LM Studio печатает сырые факты без LLM-нарратива.

---

## Этап 8. Scheduler и операционная готовность

**Что строится:**
- `scheduler/setup.py` — APScheduler: summarizer раз в час
- Экспоненциальный backoff при reconnect Telethon
- Graceful shutdown: дождаться завершения текущего батча перед остановкой
- `GET /status` — component-level health: telegram, db, lm_studio, scheduler, backlog по стадиям
- `GET /admin/metrics` — realtime_lag, backlog_by_stage, llm_parse_error_rate, quarantine_size
- `docker-compose.yml` — Postgres с pgvector, volume для `.session` файла Telethon
- `Dockerfile`
- `docs/runbooks/` — четыре runbook: LM Studio down, session corrupted, backlog growing, bad entity merge

**Артефакт:** система запускается через `docker-compose up` и работает автономно. `GET /status` показывает реальное состояние компонентов. `GET /admin/metrics` отвечает на вопрос "пайплайн работает нормально?". Runbooks покрывают четыре основных failure mode.

---

## Post-MVP: Durable Ingest Buffer

**Зачем:** при падении Postgres новые сообщения теряются — это главный operational debt системы, честно признанный в архитектуре.

**Что строится:** SQLite/WAL-файл как локальный буфер между Telethon listener и Postgres. Listener пишет в буфер атомарно; отдельный worker сбрасывает в Postgres и удаляет из буфера после подтверждения.

**Артефакт:** при перезапуске Postgres сообщения не теряются — они накоплены в буфере и сброшены после восстановления соединения.
