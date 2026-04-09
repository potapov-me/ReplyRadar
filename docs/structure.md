# Файловая структура проекта

`src`-layout: пакет изолирован от корня репозитория, случайный импорт из рабочей директории невозможен.

```
replyradar/
│
├── src/
│   └── replyradar/
│       ├── config.py              # pydantic-settings: единая точка конфигурации
│       ├── main.py                # тонкий entrypoint: импортирует app из api/app.py
│       ├── bootstrap.py           # composition root: создаёт пул, поднимает listener,
│       │                          # engine, scheduler; wiring зависимостей только здесь
│       │
│       ├── db/
│       │   ├── pool.py            # asyncpg connection pool (создаётся один раз при старте)
│       │   └── repos/             # весь SQL скрыт здесь, наружу — только типизированные методы
│       │       ├── messages.py
│       │       ├── entities.py    # включая рекурсивные CTE для графа
│       │       ├── signals.py
│       │       ├── quarantine.py  # processing_quarantine: вставка, reprocess, skip
│       │       └── audit.py       # entity_audit_log: запись и чтение истории операций
│       │
│       ├── ingestion/
│       │   ├── listener.py        # Telethon realtime listener → asyncio.Queue
│       │   └── backfill.py        # итератор iter_messages для загрузки истории
│       │
│       ├── processing/
│       │   ├── engine.py          # оркестратор: realtime queue + backfill loop,
│       │   │                      # приоритет realtime над backfill
│       │   ├── classify.py        # стадия Classify → is_signal
│       │   ├── extract.py         # стадия Extract → commitments, pending_replies, risks
│       │   ├── embed.py           # стадия Embed → pgvector
│       │   └── entity_extract.py  # стадия EntityExtract → батчевый вызов LLM
│       │
│       ├── knowledge/             # domain rules knowledge-домена (тактический DDD)
│       │   ├── activation.py      # activation policy: критерии candidate → active
│       │   ├── confidence.py      # effective_confidence(): формула затухания и весов
│       │   ├── resolution.py      # merge rules: entity resolution + safe-unmerge
│       │   ├── superseding.py     # semantics: когда факт supersedes другой, обновление счётчиков
│       │   └── graph.py           # построители транзитивных CTE-запросов
│       │
│       ├── usecases/              # orchestration: решает что, когда и зачем — не как
│       │   ├── today.py           # агрегирует pending + commitments + risks
│       │   ├── backfill.py        # запускает ingestion + processing
│       │   ├── summarize.py       # решает что суммаризировать → вызывает summarizer/
│       │   ├── people.py          # GetPersonProfile, FindConnections
│       │   └── digest.py          # решает что включать в дайджест → вызывает digest/
│       │
│       ├── llm/
│       │   ├── client.py          # единственное место вызова LiteLLM
│       │   ├── prompts/           # версионированные шаблоны промптов
│       │   │   ├── classify_v1.txt
│       │   │   ├── extract_v1.txt
│       │   │   └── entity_extract_v1.txt
│       │   └── contracts/         # Pydantic-схемы ответов LLM (типизированный контракт стадий)
│       │       ├── classify.py
│       │       ├── extract.py
│       │       └── entity_extract.py
│       │
│       ├── summarizer/
│       │   └── summarizer.py      # техника: LLM-вызов + запись в chat_summaries.
│       │                          # НЕ решает когда и зачем суммаризировать — это usecases/summarize.py
│       │
│       ├── digest/
│       │   ├── generator.py       # техника: сборка текста дайджеста из read-model
│       │   └── bot.py             # техника: доставка текста в Telegram Bot.
│       │                          # НЕ решает что включать и когда запускать — это usecases/digest.py
│       │
│       ├── scheduler/
│       │   └── setup.py           # APScheduler: summarizer раз в час
│       │
│       └── api/
│           ├── app.py             # FastAPI instance, middleware, lifespan
│           ├── deps.py            # зависимости: db connection, pagination params
│           └── routes/
│               ├── chats.py       # /chats, /backfill, /today, /pending, /commitments, /risks
│               ├── people.py      # /people — reads: db/repos напрямую; mutations: usecases/
│               ├── orgs.py        # /orgs
│               └── admin.py       # /admin/quarantine, /admin/metrics, /admin/entities/{id}/audit
│
├── tests/
│   ├── conftest.py                # фикстуры: тестовая БД, моки LLM-контрактов
│   ├── usecases/
│   ├── processing/
│   ├── knowledge/
│   └── api/
│
├── evals/                         # офлайн-проверка качества LLM-стадий
│   ├── README.md                  # процесс: golden datasets, gate перед merge prompt-изменений
│   └── datasets/                  # фиксированные наборы кейсов для regression

├── docs/
│   └── runbooks/                  # короткие операционные инструкции
│       ├── lm-studio-down.md
│       ├── session-corrupted.md
│       ├── backlog-growing.md
│       └── bad-entity-merge.md
│
├── migrations/                    # Alembic (без привязки к SQLAlchemy ORM,
│   ├── env.py                     # схема описывается в SQL миграций)
│   ├── script.py.mako
│   └── versions/
│
├── config/
│   └── default.yaml               # значения по умолчанию (LLM base_url, batch_size и т.п.)
│
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
├── CLAUDE.md
└── README.md
```

## Ключевые принципы организации

**Границы контекстов — через импорты.** Запрещённые направления: `processing/` не импортирует из `usecases/` и `api/`; `knowledge/` не знает о `processing/` и `api/`. Нарушение автоматически проверяется через `import-linter` (ADR-0015).

**Тонкий `main.py`, явный composition root.** `main.py` — только точка входа для uvicorn. Весь wiring (пул БД, listener, processing engine, scheduler) собирается в `bootstrap.py`. Это предотвращает god-object и делает компоненты тестируемыми независимо друг от друга.

**Command/query split.** Мутации (`insert_*`, `update_*`, `delete_*`, `upsert_*`) — только через `usecases/`. Read-запросы (`get_*`, `list_*`, `find_*`) из `api/routes/` могут идти напрямую в `db/repos/` без промежуточного use-case. Подробнее: ADR-0013.

**Типизированные контракты LLM-стадий.** В `llm/contracts/` — Pydantic-схемы ожидаемых ответов для каждой стадии. В `llm/prompts/` — версионированные шаблоны. Поле `prompt_version` в БД ссылается на конкретный файл. Логика разбора ответа не расползается по `classify.py`, `extract.py`, `entity_extract.py`.

**`summarizer/` и `digest/` — техническая реализация, не оркестрация.** Эти пакеты содержат только "как": построить текст, вызвать LLM, отправить в бот. Решения "что включать", "когда запускать", "что делать при ошибке" — в `usecases/summarize.py` и `usecases/digest.py`. `summarizer/` и `digest/` не импортируют из `usecases/` и не знают о расписании.

**Один вход в LLM.** Все обращения к LiteLLM — только через `llm/client.py`. Это единственное место, где знают про `base_url`, `model`, `api_key` и политику fallback при недоступности LM Studio.

**SQL скрыт в репозиториях.** Прямых SQL-запросов и обращений к пулу за пределами `db/repos/` нет. Рекурсивные CTE, pgvector-операторы и `ON CONFLICT` пишутся как явный SQL — без ORM-обёрток.

**Стадии processing — независимые модули.** Каждая стадия (`classify`, `extract`, `embed`, `entity_extract`) — отдельный файл с одной публичной функцией. Оркестратор в `engine.py` знает про порядок и флаги идемпотентности; стадии про оркестратор не знают.

**Конфигурация — одна точка.** `config.py` читает `default.yaml` и переменные окружения через pydantic-settings. Никаких захардкоженных значений в других модулях.
