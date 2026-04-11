# Файловая структура проекта

Ниже отражена текущая структура репозитория. Некоторые каталоги уже существуют как заготовки под следующие этапы, но не содержат полноценного runtime-функционала.

```text
replyradar/
├── src/replyradar/
│   ├── __main__.py               # CLI: auth, eval
│   ├── main.py                   # entrypoint для uvicorn
│   ├── bootstrap.py              # composition root
│   ├── config.py                 # settings из .env + config/default.yaml
│   ├── logging.py                # настройка логирования
│   │
│   ├── api/
│   │   ├── app.py                # FastAPI app + lifespan
│   │   ├── deps.py               # DI helpers
│   │   └── routes/
│   │       ├── status.py         # GET /status
│   │       ├── chats.py          # monitor + backfill
│   │       ├── imports.py        # Telegram Desktop import
│   │       └── admin.py          # quarantine admin
│   │
│   ├── db/
│   │   ├── pool.py
│   │   └── repos/
│   │       ├── chats.py
│   │       ├── messages.py
│   │       ├── signals.py
│   │       └── quarantine.py
│   │
│   ├── ingestion/
│   │   ├── listener.py
│   │   ├── backfill.py
│   │   └── tg_export_parser.py
│   │
│   ├── processing/
│   │   ├── engine.py
│   │   ├── classify.py
│   │   ├── extract.py
│   │   └── embed.py
│   │
│   ├── llm/
│   │   ├── client.py
│   │   ├── contracts/
│   │   │   ├── classify.py
│   │   │   └── extract.py
│   │   └── prompts/
│   │       ├── classify.py
│   │       └── extract.py
│   │
│   ├── usecases/
│   │   ├── chats.py
│   │   ├── imports.py
│   │   └── quarantine.py
│   │
│   ├── eval/                     # CLI eval runners
│   ├── summarizer/               # пока заготовка
│   ├── digest/                   # пока заготовка
│   ├── scheduler/                # пока заготовка
│   └── knowledge/                # пока заготовка
│
├── tests/
│   ├── ingestion/
│   ├── llm/
│   ├── processing/
│   ├── integration/
│   └── test_import_boundaries.py
│
├── migrations/
├── config/default.yaml
├── evals/
├── docs/
├── docker-compose.yml
├── Makefile
├── pyproject.toml
└── README.md
```

## Что важно по слоям

### `bootstrap.py` как единственная точка wiring

Создание пула БД, listener, processing engine и остальных runtime-компонентов сосредоточено в одном месте. `main.py` остаётся тонким entrypoint.

### `usecases/` для command-path

Мутации бизнес-состояния выносятся в `usecases/`, чтобы роуты не писали SQL-логику напрямую. В текущем коде это уже используется для чатов, импорта и quarantine.

### `db/repos/` как место для SQL

Повторно используемый SQL лежит в `db/repos/`. При этом в runtime всё ещё есть точечные прямые запросы через `pool` в orchestration-коде вроде `status.py` и `processing/engine.py`.

### `processing/` сейчас уже не заготовка

Это рабочий слой, который:

- batch-классифицирует backlog
- делает fallback на per-message classify
- создаёт embeddings
- извлекает commitments / pending replies / communication risks
- отправляет проблемные сообщения в quarantine

### Каталоги с future-статусом

Сейчас как заготовки или минимальные namespace-пакеты существуют:

- `knowledge/`
- `summarizer/`
- `digest/`
- `scheduler/`

Документация не должна описывать их как завершённые подсистемы.
