# Observability

Сейчас основная операционная поверхность проекта состоит из `GET /status` и quarantine-роутов. Эндпоинта `/admin/metrics` в текущем runtime нет.

## `GET /status`

Пример ответа:

```json
{
  "telegram": "connected",
  "db": "writable",
  "lm_studio": "reachable",
  "scheduler": "not_started",
  "pipeline": {
    "realtime_queue_depth": 0,
    "backlog_classify": 12,
    "backlog_extract": 5,
    "backlog_entity_extract": 0,
    "quarantine_size": 2
  }
}
```

### Поля верхнего уровня

| Поле | Возможные значения | Что значит |
|---|---|---|
| `telegram` | `connected`, `not_authorized`, `error`, `disconnected`, `not_configured` | состояние Telethon listener |
| `db` | `writable`, `error` | доступность Postgres для чтения/записи |
| `lm_studio` | `reachable`, `unreachable`, `not_configured` | доступность LLM endpoint |
| `scheduler` | сейчас всегда `not_started` | scheduler ещё не реализован |

### Поля `pipeline`

| Поле | Что измеряет |
|---|---|
| `realtime_queue_depth` | глубина `asyncio.Queue` с realtime-сообщениями |
| `backlog_classify` | сообщения без `classified_at`, не ушедшие в quarantine |
| `backlog_extract` | signal-сообщения без `extracted_at`, не ушедшие в quarantine |
| `backlog_entity_extract` | резервное поле под будущую стадию entity extraction |
| `quarantine_size` | число необработанных записей в `processing_quarantine` |

`db_detail` и `telegram_detail` могут присутствовать дополнительно, если компонент вернул ошибку.

## Как интерпретировать деградацию

### `db: error`

- API поднялся, но storage недоступен
- ingestion и processing в таком состоянии не работают
- сначала проверить Postgres и миграции

### `telegram: not_authorized`

- `.session` не найдена или невалидна
- нужно выполнить `make auth`

### `lm_studio: unreachable`

- новые сообщения продолжают сохраняться
- LLM-зависимые стадии backlog не двигаются
- после восстановления LM Studio добор пойдёт автоматически

### `quarantine_size > 0`

- часть сообщений не может пройти pipeline автоматически
- смотреть `GET /admin/quarantine`

## Quarantine operations

### Список проблемных записей

```text
GET /admin/quarantine?limit=50&offset=0
```

Ответ содержит массив `items` и `count`.

### Повторная обработка

```text
POST /admin/quarantine/{quarantine_id}/reprocess
```

Роут:

- помечает quarantine record как `reprocessed`
- очищает `*_error` у соответствующей стадии
- позволяет pipeline подобрать сообщение заново

### Пропуск

```text
POST /admin/quarantine/{quarantine_id}/skip
```

Роут помечает запись как `skipped`, не перезапуская стадию.

## Практический минимум для оператора

Стоит реагировать в первую очередь на такие сигналы:

1. `db != writable`
2. `telegram = error` или `not_authorized`
3. `lm_studio = unreachable` при растущем backlog
4. `quarantine_size > 0`
5. стабильно растущий `realtime_queue_depth`

Расширенные метрики, scheduler-health и runbooks для future-сценариев пока не внедрены.
