# ADR-0015: Формальные границы импортов между пакетами

## Статус

Принято

## Контекст

Правило "границы контекстов видны через импорты" зафиксировано в `docs/structure.md`, но остаётся социальным контрактом. Без автоматической проверки нарушения накапливаются незаметно — каждое кажется локальным исключением, в сумме они разрушают архитектурные гарантии.

## Решение

Явная карта разрешённых и запрещённых зависимостей, проверяемая тестом в CI.

### Разрешённые зависимости

```
main          → api, bootstrap
bootstrap     → db, ingestion, processing, scheduler, api
api/routes    → usecases              (command path)
api/routes    → db/repos (get_*/list_*/find_*) (query path)
api/routes    → knowledge/confidence, knowledge/graph
usecases      → db/repos
usecases      → knowledge
usecases      → llm/client
usecases      → summarizer, digest
processing    → db/repos
processing    → llm/client
processing    → knowledge/superseding, knowledge/activation
ingestion     → db/repos
knowledge     → db/repos
summarizer    → db/repos
summarizer    → llm/client
digest        → db/repos
scheduler     → usecases
```

### Запрещённые зависимости

```
processing    → usecases              # pipeline не знает о сценариях
processing    → api
knowledge     → api                   # domain rules не знают о транспорте
knowledge     → processing
knowledge     → usecases
api/routes    → db/repos (insert_*/update_*/delete_*)  # мутации только через usecases
любой модуль  → bootstrap             # composition root — точка входа, не библиотека
```

### Реализация

`tests/test_import_boundaries.py` — тест на основе `importlib` или `pytest-importlinter`. Запускается в CI на каждый PR. Нарушение = failed test = блокирующий merge.

Пример конфига для `pytest-importlinter`:

```ini
# setup.cfg
[importlinter]
root_package = replyradar

[importlinter:contract:processing-isolation]
name = Processing не импортирует usecases и api
type = forbidden
source_modules =
    replyradar.processing
forbidden_modules =
    replyradar.usecases
    replyradar.api

[importlinter:contract:knowledge-isolation]
name = Knowledge не импортирует api и processing
type = forbidden
source_modules =
    replyradar.knowledge
forbidden_modules =
    replyradar.api
    replyradar.processing
    replyradar.usecases
```

## Последствия

- Архитектурный контракт перестаёт быть review-rule и становится автоматически проверяемым инвариантом.
- Добавление новой зависимости требует явного изменения конфига — это делает архитектурные решения видимыми.
- `pytest-importlinter` добавляется в dev-зависимости.
