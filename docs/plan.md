# План разработки

Каждый этап завершается рабочим артефактом, который можно потрогать руками. Следующий этап начинается только после того, как артефакт предыдущего работает.

---

## Этап 1. Фундамент

**Что строится:**
- `src`-layout, `pyproject.toml` с зависимостями
- `config.py` — pydantic-settings, читает `config/default.yaml` и env
- `db/pool.py` — asyncpg connection pool
- Alembic: первая миграция с полной схемой БД (все таблицы из `architecture.md`)
- `main.py` — FastAPI lifespan: открывает пул, применяет pending миграции, закрывает пул

**Артефакт:** `uvicorn src.replyradar.main:app` стартует, подключается к Postgres, `GET /status` возвращает `{"db": "ok"}`. Схема БД полностью развёрнута через `alembic upgrade head`.

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
- `llm/client.py` — LiteLLM wrapper, единственная точка вызова; при недоступности LM Studio бросает `LLMUnavailableError`
- `processing/classify.py` — определяет `is_signal`, пишет `classified_at` или `classify_error`
- `processing/extract.py` — извлекает commitments, pending_replies, communication_risks; пишет `extracted_at` или `extract_error`
- `processing/embed.py` — pgvector embedding; пишет `embedded_at` или `embed_error`
- `processing/engine.py` — оркестратор: realtime queue + backfill loop, приоритет realtime
- `db/repos/signals.py` — upsert по `source_fingerprint` для commitments и pending_replies

**Артефакт:** после backfill в таблицах `commitments`, `pending_replies`, `communication_risks` появляются записи. При недоступности LM Studio сообщения остаются с `NULL` timestamp и обрабатываются при следующем запуске.

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
- `processing/entity_extract.py` — батчевый LLM-вызов на группу сообщений; результат — список сущностей, фактов и связей
- `knowledge/resolution.py` — сопоставление новой сущности с существующими: embedding similarity → при > 0.85 LLM подтверждает merge
- `db/repos/entities.py` — upsert entities, facts, relations; обновление `corroboration_count` через `entity_fact_sources`
- Backfill entity extraction: `WHERE entities_extracted_at IS NULL`

**Артефакт:** после прогона `entity_extract` по истории чатов таблицы `entities`, `entity_facts`, `entity_relations` заполнены. Один человек, упомянутый разными именами в разных чатах, склеивается в одну запись.

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
- `docker-compose.yml` — Postgres с pgvector, volume для `.session` файла Telethon
- `Dockerfile`

**Артефакт:** система запускается через `docker-compose up` и работает автономно: слушает Telegram, обрабатывает сообщения, обновляет резюме по расписанию, доступна по API. Перезапуск контейнера не теряет состояние и не создаёт дублей.
