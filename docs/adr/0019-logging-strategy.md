# ADR-0019: Стратегия логирования

## Статус

Принято

## Контекст

Система обрабатывает личные переписки. Ключевой инвариант (из ADR-0001):
**тексты сообщений никогда не попадают в stdout-логи** — только ID, метрики, статусы.
Нарушение этого инварианта — утечка приватных данных.

Исходная реализация `logging.py` имела несколько недостатков:
- нет контроля над шумными сторонними библиотеками (telethon, litellm, httpx);
- нет поддержки структурированного формата (нужен для Docker / log-aggregation);
- не вызывалась из CLI-пути (`__main__.py`);
- уровень логирования нельзя изменить без правки кода.

## Решение

### Единая точка конфигурации

`replyradar/logging.py` — единственный модуль, где вызывается `logging.basicConfig`
или настраиваются handlers. Все остальные модули получают логгер только через
`logging.getLogger(__name__)` и никогда не настраивают его сами.

`configure_logging(config)` вызывается однократно при старте процесса:
- `main.py` — путь uvicorn: `configure_logging(get_settings().log)`
- `__main__.py` — путь CLI: `configure_logging()` (читает settings самостоятельно)

### Форматы вывода

| Формат | Вид | Когда использовать |
|--------|-----|--------------------|
| `text` | `2026-04-10 12:34:56 INFO [replyradar.engine] ProcessingEngine started` | Локальная разработка (default) |
| `json` | `{"ts": "...", "level": "INFO", "logger": "...", "message": "..."}` | Docker, log-aggregation (Loki, Datadog) |

Переключение через `LOG__FORMAT=json` в `.env` или `log.format: json` в конфиге.

### Уровень логирования

Управляется через `LOG__LEVEL` в `.env` (или `log.level` в `config/default.yaml`).
Значения: `DEBUG | INFO | WARNING | ERROR`. Default: `INFO`.

### Подавление шума сторонних библиотек

Следующие логгеры принудительно переводятся на `WARNING`:

| Логгер | Причина |
|--------|---------|
| `telethon` | DEBUG-поток MTProto-фреймов |
| `litellm`, `litellm.utils`, `litellm.main` | Детали HTTP к LM Studio |
| `httpx`, `httpcore` | Тело запросов/ответов LLM |
| `asyncpg` | Детали SQL-запросов |
| `uvicorn.access` | HTTP-доступ не нужен в business-логах |

### Инвариант приватности

Никакой код в `replyradar.*` **не должен** логировать `msg.text`, `sender_name`
или любое другое содержимое сообщений. Разрешено логировать:
- числовые идентификаторы: `msg_id`, `chat_id`, `message_id`
- метрики и статусы: `is_signal`, `stage`, `retry_count`, `quarantine_size`
- технические события: `ProcessingEngine started`, `backfill batch size=N`

Этот инвариант проверяется код-ревью, а не автоматически.

### Зависимость

`python-json-logger` — лёгкая библиотека (~300 строк) для JSON-формата.
Если не установлена — `configure_logging` делает fallback на text-формат с предупреждением.

## Последствия

- `LOG__LEVEL=DEBUG` в `.env` включает детальные логи для отладки без изменения кода.
- `LOG__FORMAT=json` готовит систему к интеграции с Docker logging driver и Loki (этап 8).
- Uvicorn форматирует свои логи в том же стиле, что и `replyradar.*` — единый вид в терминале.
- Добавление нового модуля требует только `logger = logging.getLogger(__name__)` — никаких других действий.
