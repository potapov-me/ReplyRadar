# ADR-0008: asyncpg и raw SQL вместо SQLAlchemy ORM

## Статус

Принято

## Контекст

Проект требует нетривиальных запросов к Postgres:
- рекурсивные CTE для транзитивного обхода графа сущностей
- `INSERT ... ON CONFLICT DO NOTHING` для идемпотентного ingestion
- pgvector similarity search для entity resolution
- сложные агрегаты для confidence scoring

SQLAlchemy ORM решает эти задачи через `text()` или многословные query builder-конструкции — то есть фактически возвращается к raw SQL, но с дополнительным слоем абстракции.

## Решение

Использовать **asyncpg** как драйвер и **raw SQL** в репозиториях. Миграции — через **Alembic** (работает независимо от ORM).

## Последствия

- SQL пишется явно — рекурсивные CTE, pgvector-операторы и `ON CONFLICT` читаются без сюрпризов.
- Нет магии ORM: нет lazy loading, нет неожиданных N+1, нет implicit transactions.
- Весь SQL сосредоточен в `db/repos/` — остальные модули его не видят.
- Alembic управляет миграциями без привязки к моделям SQLAlchemy; схема описывается в SQL-файлах миграций.
- Больше boilerplate в репозиториях по сравнению с ORM — принято осознанно.
