# Ingestion: выкачивание сообщений

Ingestion — первый слой системы. Его задача: забрать сообщения из Telegram и положить в Postgres так, чтобы Processing Engine мог их обрабатывать.

---

## Два режима

### Realtime (listener)

`TelegramListener` держит постоянное MTProto-соединение через Telethon. При получении нового сообщения в мониторируемом чате:

1. Идентифицирует чат по `telegram_id` → находит `chat_id` в Postgres
2. Сохраняет сообщение (`INSERT ... ON CONFLICT DO NOTHING`)
3. Кладёт `db_id` сообщения в `asyncio.Queue` → Processing Engine забирает немедленно

Listener запускается при старте приложения (`bootstrap.py`). Если `TELEGRAM__API_ID` не задан или сессия не авторизована — listener не запускается, `GET /status` покажет `telegram: not_configured / not_authorized`.

### Backfill (история)

`BackfillRunner` загружает историю чатов через `iter_messages` — от старых сообщений к новым. Используется чтобы обработать переписку, накопившуюся до подключения системы.

---

## Первый запуск: пошаговая инструкция

### 1. Получить Telegram API credentials

Зайти на [my.telegram.org](https://my.telegram.org) → **API development tools** → создать приложение. Сохранить `api_id` (число) и `api_hash` (строка).

### 2. Настроить .env

```bash
cp .env.example .env
```

Заполнить в `.env`:

```env
TELEGRAM__API_ID=12345678
TELEGRAM__API_HASH=your_api_hash_here
```

### 3. Авторизовать сессию

```bash
make auth
# или: uv run python -m replyradar auth
```

Telethon запросит номер телефона и код подтверждения. После успешной авторизации появится файл `replyradar.session` в корне проекта. Этот файл — ваши данные аутентификации, не коммитить.

### 4. Запустить API

```bash
make dev
```

Проверить состояние:

```
GET /status
```

Ожидаемый ответ при успешном подключении:

```json
{
  "telegram": "connected",
  "db": "writable",
  ...
}
```

### 5. Добавить чат для мониторинга

```
POST /chats/{telegram_id}/monitor
```

`telegram_id` — числовой ID чата или пользователя в Telegram. Для публичных чатов можно получить через `@username`. Для личных диалогов — через любой Telegram-клиент с отображением ID.

Если listener подключён, система проверит что такой ID существует и вернёт 422 если не найден.

Ответ содержит запись чата из БД. Повторный вызов идемпотентен.

### 6. Запустить backfill

Для конкретного чата:

```
POST /backfill
{"telegram_id": 123456789}
```

Для всех мониторируемых чатов сразу:

```
POST /backfill
{}
```

Запрос возвращает `202 Accepted` немедленно. Backfill работает в фоне.

### 7. Следить за прогрессом

```
GET /backfill/status
```

Пример ответа:

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

Возможные статусы чата: `pending`, `running`, `completed`, `error`.

---

## Детали реализации

### ON CONFLICT DO NOTHING

Все вставки сообщений идемпотентны — уникальный ключ `(chat_id, telegram_msg_id)`. Если backfill пересекается с realtime-потоком или запускается повторно, дублей не возникает.

### Батчевая обработка

Backfill читает историю батчами по `backfill_batch_size` сообщений (по умолчанию 20, настраивается в `config/default.yaml`). После каждого батча:
- записи сохраняются в Postgres
- event loop уступает управление — realtime-сообщения не блокируются на время backfill

### Ограничение параллелизма

Параметр `backfill_concurrency` (по умолчанию 1) ограничивает количество чатов, backfill которых идёт одновременно. При `concurrency=1` чаты обрабатываются последовательно. При `concurrency=2` — два чата параллельно, остальные ждут в очереди.

Меняется в `config/default.yaml`:

```yaml
processing:
  backfill_concurrency: 2
  backfill_batch_size: 20
```

### Деградированный режим

| Ситуация | Поведение |
|----------|-----------|
| БД недоступна при старте | Listener не запускается; `/status` → `db: error`; все ingestion-эндпоинты → 503 |
| Telegram не настроен (`api_id=0`) | Listener не запускается; `POST /backfill` → 503 |
| Сессия не авторизована | Listener переходит в `not_authorized`; `GET /status` → `telegram: not_authorized` |
| LM Studio недоступен | Ingestion работает нормально; сообщения копятся с `classified_at IS NULL`; обработка продолжится при следующем запуске |

### Что не делает ingestion

- Не вызывает `mark_read()` — статус прочтения в Telegram не меняется
- Не логирует тексты сообщений — только ID, метрики, статусы
- Не отправляет ничего от имени пользователя

---

## Troubleshooting

**`telegram: not_authorized` после `make auth`**

Проверить `TELEGRAM__SESSION_DIR` в `.env` — должен указывать туда, где лежит `.session` файл.

**Backfill завершился с `error`**

Смотреть `GET /backfill/status` → поле `error`. Частая причина: Telegram FloodWait (слишком много запросов). Telethon обрабатывает его автоматически с задержкой, но при очень больших чатах backfill может занять значительное время.

**Сообщения не появляются в realtime**

Проверить `GET /status` → `telegram: connected`. Если подключён — убедиться что чат добавлен через `POST /chats/{id}/monitor` до получения новых сообщений. Уже существующие сообщения realtime не захватывает — для них нужен backfill.
