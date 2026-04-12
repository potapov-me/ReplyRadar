# Ingestion

Ingestion забирает сообщения из Telegram и кладёт их в Postgres так, чтобы их мог подобрать `ProcessingEngine`.

## Три режима

### 1. Realtime listener

`TelegramListener` поднимается при старте приложения, если:

- доступна БД
- заданы `TELEGRAM__API_ID` и `TELEGRAM__API_HASH`
- Telethon-сессия уже авторизована

Что делает listener:

1. Загружает из БД список monitor-чатов
2. Подписывается на `events.NewMessage`
3. Для нового сообщения из monitor-чата сохраняет его в `messages`
4. Кладёт `db_id` в `asyncio.Queue` для немедленной обработки

### 2. Backfill через Telegram

`BackfillRunner` запускается по `POST /backfill`, если listener подключён. Он:

- читает историю через `iter_messages(..., reverse=True)`
- сохраняет сообщения батчами
- обновляет состояние для `GET /backfill/status`

Backfill идемпотентен: повторный запуск не создаёт дублей.

### 3. Import из Telegram Desktop export

`POST /import/telegram-export` принимает `result.json` и импортирует сообщения напрямую в БД.

Этот путь нужен когда:

- нет live-соединения с Telegram
- Telethon session ещё не настроена
- нужно загрузить историю офлайн
- backfill через MTProto нежелателен

## Пошаговый запуск

### Настройка Telegram

1. Получить `api_id` и `api_hash` на `https://my.telegram.org`
2. Записать их в `.env`

```env
TELEGRAM__API_ID=12345678
TELEGRAM__API_HASH=your_api_hash
```

3. Авторизовать сессию:

```bash
make auth
```

По умолчанию будет создан файл `replyradar.session` в директории из `TELEGRAM__SESSION_DIR`/`TELEGRAM__SESSION_NAME`.

### Запуск API

```bash
make dev
```

Проверка:

```bash
curl http://localhost:8000/status
```

Ожидаемое состояние при успешном подключении:

```json
{
  "telegram": "connected",
  "db": "writable",
  "lm_studio": "reachable",
  "scheduler": "not_started"
}
```

## Monitor и backfill

### Добавить чат в мониторинг

```text
POST /chats/{telegram_id}/monitor
```

Роут:

- требует `telegram: connected`
- проверяет, что чат реально существует
- создаёт или обновляет запись в `chats`
- добавляет чат в runtime-фильтр listener без перезапуска

### Запустить backfill

Для одного чата:

```json
POST /backfill
{"telegram_id": 123456789}
```

Для всех monitor-чатов:

```json
POST /backfill
{}
```

Если Telegram listener недоступен, `POST /backfill` не тянет историю из Telegram, а будит DB backlog processing.

### Смотреть прогресс backfill

```text
GET /backfill/status
```

Пример:

```json
{
  "status": "running",
  "chats": [
    {
      "telegram_id": 123456789,
      "status": "running",
      "messages_saved": 840,
      "started_at": "2026-04-10T09:00:00+00:00",
      "completed_at": null,
      "error": null
    }
  ]
}
```

## Импорт Telegram Desktop export

### Вызов API

`POST /import/telegram-export` принимает multipart upload:

- `file`: `result.json`
- `monitor`: query-параметр, по умолчанию `false`

Пример ответа:

```json
[
  {
    "telegram_id": -1001234567890,
    "title": "Example chat",
    "is_monitored": false,
    "messages_parsed": 3420,
    "messages_imported": 3418,
    "messages_skipped": 2
  }
]
```

Роут поддерживает:

- экспорт одного чата
- полный экспорт аккаунта с `chats.list`

### Нормализация

Парсер:

- превращает `from_id` вроде `user123` или `channel123` в bigint
- собирает plain text из Telegram JSON blocks
- пропускает service messages
- нормализует supergroup/channel ID в канонический MTProto вид с префиксом `-100`

## Гарантии и ограничения

### Что гарантируется

- вставка сообщений идемпотентна
- realtime и backfill можно запускать повторно
- импорт работает без Telegram-соединения
- ingestion не меняет read-status и не отправляет сообщения от имени пользователя

### Текущие ограничения

- retry-счётчики processing живут в памяти процесса
- файл импорта читается в память целиком
- лимит размера `result.json` задаётся через `TG_IMPORT__MAX_FILE_SIZE_MB`
- при недоступной БД ingestion не буферизует сообщения локально

### Производительность backfill

`_flush_buffer` кеширует `get_sender()` по `sender_id` внутри одного батча. Для типичного чата (один-два активных участника) это 1–2 Telegram RPC на батч вместо N.

## Деградированные режимы

| Ситуация | Поведение |
|---|---|
| БД недоступна | приложение стартует, но ingestion и processing не поднимаются |
| Telegram не настроен | import и `/status` работают, listener не стартует |
| Сессия не авторизована | `/status` показывает `telegram: not_authorized` |
| LM Studio недоступен | ingestion идёт, backlog processing откладывается |

## Что не входит в ingestion

- query API поверх сигналов
- summarizer и digest
- scheduler
- knowledge graph
