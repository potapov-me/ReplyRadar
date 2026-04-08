# ADR-0013: Разделение command и query путей

## Статус

Принято

## Контекст

По мере роста `usecases/` возникает соблазн пропускать через него все запросы к данным — в том числе простые read-only. Это создаёт ненужную косвенность для запросов, которые не имеют побочных эффектов. Одновременно мутации рискуют просочиться напрямую из роутов в репозитории, минуя use-case слой.

## Решение

Явное разделение на два пути без полного CQRS:

**Command path (write):** `api/routes/` → `usecases/` → `db/repos/` + `knowledge/`  
Все операции с побочными эффектами (backfill, activate, mute, merge, summarize, relate) проходят через `usecases/`. Роут не знает деталей реализации.

**Query path (read):** `api/routes/` → `db/repos/` напрямую  
Read-only запросы (`GET /today`, `GET /people/{id}`, `GET /people/{id}/connections`) могут обращаться к `db/repos/` без промежуточного use-case слоя. Repos предоставляют типизированные read-методы; бизнес-правил в них нет.

### Правило разграничения

Вопрос для любого эндпоинта: "Меняет ли этот запрос состояние системы?"
- Да → command path через `usecases/`
- Нет → query path напрямую в `db/repos/`

Confidence calculation и graph traversal (`knowledge/confidence.py`, `knowledge/graph.py`) вызываются из query path — они не имеют побочных эффектов.

### Именование

В `db/repos/` методы разделяются по префиксу:
- `get_*`, `list_*`, `find_*`, `count_*` — query methods, без side effects
- `insert_*`, `update_*`, `upsert_*`, `delete_*` — command methods, только для вызова из `usecases/`

## Последствия

- Query path проще тестировать: нет моков use-case слоя.
- Command path имеет единственную точку входа для каждой операции: проще audit и idempotency.
- Нет overhead полного CQRS (отдельные read/write модели, event bus).
- Нарушение: роут вызывает `update_*` метод репо напрямую — сигнал для code review.
