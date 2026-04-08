# Architecture

## Принципы

- **Ingestion с ограниченными гарантиями** — работает независимо от LLM; при падении Postgres теряет сообщения (история восстанавливается через backfill)
- **Обработка идемпотентна** — можно прервать, перезапустить, повторить в любой момент
- **Postgres — единственный источник истины** — очередь только транспорт, не состояние
- **Деградация явная** — каждый компонент знает, что делать при отказе соседа
- **Никаких пользовательских текстов в логах** — в stdout только ID, метрики, статусы

---

## Высокоуровневая схема

```
Telegram ──► Telethon Listener ──► messages (raw, immutable)
                                          │
                              ┌───────────┴───────────┐
                              │                       │
                         realtime                 backfill
                         trigger                  trigger
                              └───────────┬───────────┘
                                          │
                                   Processing Engine
                                  (один и тот же код)
                                          │
                         ┌────────────────┼────────────────┐
                         ▼                ▼                ▼
                     Classify          Extract          Embed
                  (is_signal)   (commitments,       (pgvector)
                                pending_replies,
                                 risks)
                                          │
                                   Summarizer
                                (раз в час / по запросу)
                                          │
                                      Postgres
                                     + pgvector
                                    ▲          ▲
                                    │          │
                             Digest Gen      FastAPI
                           (CLI по запросу) (API сценариев)
                                    │          │
                             Telegram Bot   React (позже)
```

---

## Компоненты и их границы

### Telegram Listener — критический путь
Единственный компонент, отказ которого означает потерю данных.

- **Telethon** (MTProto, пользовательский аккаунт)
- `.session` файл в Docker volume `/data/session`
- При первом подключении чата — полная выгрузка истории (`iter_messages`, без лимита, от старых к новым)
- При обрыве соединения — автоматический reconnect с экспоненциальным backoff
- Дубли при пересечении истории и realtime stream — защита через `INSERT ... ON CONFLICT (telegram_message_id) DO NOTHING`
- `mark_read()` и `send_read_acknowledge()` **нигде не вызываются**

Политика отказа:
- потеря Telegram-соединения → reconnect, сообщения не теряются (Telegram хранит историю)
- недоступность БД → ingestion best-effort: сообщения теряются, история восстанавливается вручную через backfill из Telegram

Post-MVP: durable ingest buffer (SQLite/WAL-файл) — первый кандидат на усиление при ежедневном использовании.

### Движок обработки — режим с ограниченными гарантиями
Один и тот же код обслуживает realtime и backfill. Разница только в источнике задач.

**Источник задач:**
- realtime: `asyncio.Queue`, куда Listener кладёт новые message_id
- backfill: запрос к БД `WHERE classified_at IS NULL ORDER BY timestamp ASC`

**Приоритет:** realtime > backfill. Если realtime queue непуста, backfill ждёт.

**Concurrency backfill:** ограничен одним воркером (конфиг `backfill.concurrency = 1`).

### Стадии обработки

Каждая стадия пишет результат в БД и ставит timestamp. Упавшая стадия оставляет timestamp NULL — будет подхвачена при следующем запуске.

| Стадия | Флаг на `messages` | Условие запуска | При ошибке |
|---|---|---|---|
| Classify | `classified_at`, `classify_error` | всегда | пишет `classify_error`, retry при следующем запуске |
| Extract | `extracted_at`, `extract_error` | `is_signal = true` | пишет `extract_error`, retry |
| Embed | `embedded_at`, `embed_error` | после classify | пишет `embed_error`, retry |

Summary — не per-message, а per-chat. Обновляется отдельно.

**Частичный успех:** каждая стадия независима. Если extract упал — classify и embed не откатываются. При следующем запуске упавшая стадия будет перезапущена, успешные — пропущены.

### LLM — все локальные
Все вызовы идут в **LM Studio** на локальной машине. LiteLLM используется как единый интерфейс.

```yaml
llm:
  base_url: http://host.docker.internal:1234/v1
  model: local-model
  api_key: lm-studio

embedding:
  provider: lmstudio
  model: text-embedding-nomic-embed-text-v1.5
  base_url: http://host.docker.internal:1234/v1

backfill:
  batch_size: 20
  delay_between_batches_ms: 0
```

Политика отказа LLM:
- LM Studio недоступен → сообщения попадают в ingestion, обработка откладывается
- все timestamp'ы остаются NULL
- при следующем запуске обработка продолжается автоматически

### Summarizer — batched
Summary обновляется:
- по расписанию: раз в час (APScheduler)
- по запросу: `POST /chats/{id}/summarize`

### Digest Generator
MVP: **operator-invoked workflow**.

- запускается вручную из CLI
- строится из стабильной read-model
- при недоступности LM Studio печатает сырые факты без LLM-нарратива

### FastAPI — API сценариев

```
GET  /today
GET  /pending
GET  /commitments
GET  /risks
GET  /chats/{id}/summary
POST /chats/{id}/monitor
POST /backfill
GET  /backfill/status
POST /chats/{id}/summarize
GET  /status
```

---

## База данных

```sql
chats
  id              bigint PK
  telegram_id     bigint UNIQUE
  title           text
  is_monitored    boolean DEFAULT false
  history_loaded  boolean DEFAULT false
  created_at      timestamptz

messages
  id              bigint PK
  chat_id         bigint FK → chats
  telegram_msg_id bigint
  sender_id       bigint
  sender_name     text
  timestamp       timestamptz
  text            text
  reply_to_id     bigint
  is_signal       boolean
  classified_at   timestamptz
  classify_error  text
  extracted_at    timestamptz
  extract_error   text
  embedded_at     timestamptz
  embed_error     text
  embedding       vector(768)
  UNIQUE(chat_id, telegram_msg_id)

chat_summaries
  chat_id              bigint PK FK → chats
  summary              text
  key_topics           text[]
  importance_score     float
  updated_at           timestamptz
  model                text
  prompt_version       text
  source_window_start  timestamptz
  source_window_end    timestamptz
  is_full_rebuild      boolean
  embedding            vector(768)

commitments
  id                uuid PK
  source_fingerprint text UNIQUE
  closure_reason    text
  chat_id           bigint FK
  message_id        bigint FK
  author            text
  target            text
  text              text
  due_hint          text
  status            text
  status_changed_at timestamptz
  superseded_at     timestamptz
  inactive_reason   text
  extraction_model  text
  prompt_version    text
  embedding         vector(768)

pending_replies
  id                uuid PK
  source_fingerprint text UNIQUE
  chat_id           bigint FK
  message_id        bigint FK
  reason            text
  urgency           text
  resolved_at       timestamptz
  superseded_at     timestamptz
  inactive_reason   text
  extraction_model  text
  prompt_version    text

communication_risks
  id               uuid PK
  chat_id          bigint FK
  message_id       bigint FK
  type             text
  confidence       float
  explanation      text
  expired_at       timestamptz
  extraction_model text
  prompt_version   text
```

---

## Data Lifecycle

### Retention
- Raw messages — бессрочно
- Embeddings — удаляются каскадно вместе с сообщением
- Superseded facts — бессрочно для аудита
- Логи — stdout, не персистируются системой

### Удаление чата
`DELETE /chats/{id}` удаляет raw и derived данные физически, включая superseded записи.

### Резервное копирование
Ответственность пользователя: `pg_dump` или snapshot Docker volume.

---

## Quality Evaluation

Для MVP — ручная офлайн-проверка на 2–3 чатах с фиксацией промахов в `evals/`.
