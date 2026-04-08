# Файловая структура проекта

`src`-layout: пакет изолирован от корня репозитория, случайный импорт из рабочей директории невозможен.

```
replyradar/
│
├── src/
│   └── replyradar/
│       ├── config.py              # pydantic-settings: единая точка конфигурации
│       ├── main.py                # точка входа: собирает asyncio event loop,
│       │                          # регистрирует FastAPI, запускает scheduler
│       │
│       ├── db/
│       │   ├── pool.py            # asyncpg connection pool (создаётся один раз при старте)
│       │   └── repos/             # весь SQL скрыт здесь, наружу — только типизированные методы
│       │       ├── messages.py
│       │       ├── entities.py    # включая рекурсивные CTE для графа
│       │       └── signals.py
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
│       ├── knowledge/
│       │   ├── resolution.py      # entity resolution: embedding similarity + LLM merge
│       │   ├── confidence.py      # effective_confidence(): формула затухания и весов
│       │   └── graph.py           # построители транзитивных CTE-запросов
│       │
│       ├── llm/
│       │   └── client.py          # единственное место вызова LiteLLM;
│       │                          # все остальные модули импортируют только отсюда
│       │
│       ├── summarizer/
│       │   └── summarizer.py      # per-chat summary: по расписанию и по запросу
│       │
│       ├── digest/
│       │   ├── generator.py       # строит текст дайджеста из read-model
│       │   └── bot.py             # доставка в Telegram Bot
│       │
│       ├── scheduler/
│       │   └── setup.py           # APScheduler: summarizer раз в час
│       │
│       └── api/
│           ├── app.py             # FastAPI instance, middleware, lifespan
│           ├── deps.py            # зависимости: db session, pagination params
│           └── routes/
│               ├── chats.py       # /chats, /backfill, /today, /pending, /commitments, /risks
│               ├── people.py      # /people — Entity Knowledge Graph API
│               └── orgs.py        # /orgs
│
├── tests/
│   ├── conftest.py                # фикстуры: тестовая БД, моки LLM
│   ├── processing/
│   ├── knowledge/
│   └── api/
│
├── evals/                         # ручная офлайн-проверка качества LLM-стадий
│   └── README.md
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

**Один вход в LLM.** Все обращения к LiteLLM — только через `llm/client.py`. Это единственное место, где знают про `base_url`, `model`, `api_key` и политику fallback при недоступности LM Studio.

**SQL скрыт в репозиториях.** Модули `processing/`, `knowledge/`, `api/` работают через `db/repos/`. Прямых SQL-запросов и обращений к пулу за пределами `db/` нет. Рекурсивные CTE, pgvector-операторы и `ON CONFLICT` пишутся как явный SQL — без ORM-обёрток.

**Стадии processing — независимые модули.** Каждая стадия (`classify`, `extract`, `embed`, `entity_extract`) — отдельный файл с одной публичной функцией. Оркестратор в `engine.py` знает про порядок и флаги идемпотентности; стадии про оркестратор не знают.

**Конфигурация — одна точка.** `config.py` читает `default.yaml` и переменные окружения через pydantic-settings. Никаких захардкоженных значений в других модулях.
