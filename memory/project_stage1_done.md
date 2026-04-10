---
name: Этап 1 завершён
description: Этап 1 плана разработки реализован — src-layout, config, db pool, bootstrap, API с /status, Alembic схема, import boundaries
type: project
---

Этап 1 плана (`docs/plan.md`) полностью реализован.

**Why:** Нужен рабочий фундамент перед Этапом 2 (Ingestion).

**Что сделано:**
- `src`-layout: `src/replyradar/` пакет, hatchling build backend в pyproject.toml
- `config/default.yaml` — policy-as-code (ADR-0014): пороги активации, уверенности, processing параметры
- `src/replyradar/config.py` — pydantic-settings, читает YAML + env vars + .env с приоритетом env > .env > yaml
- `src/replyradar/db/pool.py` — asyncpg connection pool
- `src/replyradar/bootstrap.py` — composition root
- `src/replyradar/api/app.py` — FastAPI + lifespan
- `src/replyradar/api/routes/status.py` — GET /status с component-level состоянием
- `migrations/` — Alembic с async asyncpg, миграция 0001 с полной схемой БД (все таблицы из architecture.md)
- `tests/test_import_boundaries.py` + `setup.cfg` — import-linter контракты
- `.env.example` — документация env vars для переопределения БД URL

**Артефакт:**
- `uvicorn src.replyradar.main:app` стартует
- `GET /status` возвращает component-level состояние
- `alembic upgrade head` разворачивает схему (нужна запущенная Postgres)
- `pytest tests/test_import_boundaries.py` проходит

**How to apply:** При работе с Этапом 2 — запускаться через `uvicorn src.replyradar.main:app`, схему применять через `alembic upgrade head`.
