# Code Review: этап 1

## Findings

### 1. `GET /status` недостижим при недоступной БД, хотя именно этот сценарий endpoint должен диагностировать

Сейчас приложение поднимает пул в `lifespan`, а `lifespan` вызывается до старта сервера. Если `asyncpg.create_pool(...)` не подключится, `uvicorn` завершит запуск и до `GET /status` дело вообще не дойдёт.

- `src/replyradar/api/app.py:11-17`
- `src/replyradar/bootstrap.py:14-18`
- `src/replyradar/api/routes/status.py:9-15`

Почему это важно:
- артефакт этапа 1 сформулирован как "`uvicorn ...` стартует, `GET /status` возвращает component-level состояние"
- текущая реализация не даёт отразить `db = "error"` в самом частом деградированном сценарии, потому что приложение не стартует вовсе

Что исправить:
- не делать успешное подключение к Postgres обязательным условием старта FastAPI
- хранить состояние компонента отдельно от live-connection и позволить `/status` отвечать даже при failed bootstrap

### 2. Alembic и приложение читают разные переменные окружения для DSN

Приложение читает `DATABASE__URL` через `pydantic-settings`, а Alembic смотрит только в `DATABASE_URL`. В результате миграции и runtime легко направить в разные базы.

- `src/replyradar/config.py:74-103`
- `config/default.yaml:45`
- `migrations/env.py:21-27`
- `alembic.ini:2-4`

Почему это важно:
- этап 1 обещает "схема развёрнута"
- на практике можно применить миграции в одну БД, а приложение подключить к другой, и проблема проявится только на старте или в `/status`

Что исправить:
- использовать единый источник конфигурации для app и Alembic
- как минимум поддержать `DATABASE__URL` в `migrations/env.py`, раз это уже задокументировано и используется приложением

### 3. Архитектурный тест не покрывает обязательный запрет `routes -> repos`

План этапа 1 требует тестом зафиксировать три границы: `processing → usecases`, `routes → repos`, `knowledge → api`. В конфиге import-linter описаны только две, причём запрета `routes -> repos` нет вообще.

- `docs/plan.md:14`
- `setup.cfg:6-23`
- `tests/test_import_boundaries.py:13-24`

Почему это важно:
- один из ключевых инвариантов этапа вообще не проверяется
- будущий прямой импорт `replyradar.db.repos` из `api.routes` не сломает CI, хотя по плану должен

Что исправить:
- добавить отдельный contract для `replyradar.api.routes -> replyradar.db.repos`
- оставить `knowledge -> api` как явный контракт, а не только как часть более широкого ограничения

### 4. Миграция использует `gen_random_uuid()` без явного включения расширения/зависимости для этой функции

Первая миграция создаёт `vector`, но UUID defaults почти во всех таблицах завязаны на `gen_random_uuid()`. Для этой функции требуется корректная поддержка на целевом Postgres, иначе схема формально применится не везде или вставки начнут падать позже.

- `migrations/versions/0001_initial_schema.py:17`
- `migrations/versions/0001_initial_schema.py:80`
- `migrations/versions/0001_initial_schema.py:101`
- `migrations/versions/0001_initial_schema.py:126`
- `migrations/versions/0001_initial_schema.py:173`
- `migrations/versions/0001_initial_schema.py:189`
- `migrations/versions/0001_initial_schema.py:204`
- `migrations/versions/0001_initial_schema.py:226`
- `migrations/versions/0001_initial_schema.py:243`

Почему это важно:
- этап 1 обещает "первая миграция с полной схемой БД"
- сейчас миграция явно подготавливает только `vector`, а зависимость для UUID generation остаётся неявной

Что исправить:
- либо явно создавать нужное расширение в миграции
- либо зафиксировать минимальную версию Postgres, на которой `gen_random_uuid()` гарантированно доступна без дополнительных действий

## Assumptions

- ревью выполнено по артефактам этапа 1 из `docs/plan.md`, без оценки этапов 2+
- замечания основаны на текущем коде репозитория, а не на предполагаемом CI-окружении

## Checks

- `pytest -q` падает: `lint-imports не найден в PATH`
- `python3 -m compileall src tests migrations` проходит
