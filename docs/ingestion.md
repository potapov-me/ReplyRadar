# Ingestion: выкачивание сообщений

Ingestion — первый слой системы. Его задача: забрать сообщения из Telegram и положить в Postgres так, чтобы Processing Engine мог их обрабатывать.

---

## Три режима

### Realtime (listener)

`TelegramListener` держит постоянное MTProto-соединение через Telethon. При получении нового сообщения в мониторируемом чате:

1. Идентифицирует чат по `telegram_id` → находит `chat_id` в Postgres
2. Сохраняет сообщение (`INSERT ... ON CONFLICT DO NOTHING`)
3. Кладёт `db_id` сообщения в `asyncio.Queue` → Processing Engine забирает немедленно

Listener запускается при старте приложения (`bootstrap.py`). Если `TELEGRAM__API_ID` не задан или сессия не авторизована — listener не запускается, `GET /status` покажет `telegram: not_configured / not_authorized`.

### Backfill (история)

`BackfillRunner` загружает историю чатов через `iter_messages` — от старых сообщений к новым. Используется чтобы обработать переписку, накопившуюся до подключения системы.

### Import (ручная загрузка экспорта)

Загрузка `result.json` из Telegram Desktop. Используется когда:
- нет активного Telegram-соединения (оффлайн-сценарий, первоначальная настройка)
- backfill нецелесообразен из-за FloodWait на больших чатах
- нужно подтянуть историю до регистрации сессии

Работает через `POST /import/telegram-export` — без запущенного listener'а.

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
| Import без Telegram-соединения | `POST /import/telegram-export` работает независимо от состояния listener'а |
| Файл > 200 МБ | `POST /import/telegram-export` → 413; используйте backfill или разбейте экспорт вручную |

### Что не делает ingestion

- Не вызывает `mark_read()` — статус прочтения в Telegram не меняется
- Не логирует тексты сообщений — только ID, метрики, статусы
- Не отправляет ничего от имени пользователя

---

## Import: ручная загрузка экспорта Telegram

### Как получить экспорт

В Telegram Desktop: **Настройки → Продвинутые → Экспорт данных Telegram** → выбрать нужный чат → формат JSON → снять все галки кроме «Личные сообщения» / «Сообщения группы». Telegram сохранит архив с `result.json` в корне.

### Загрузка

```
POST /import/telegram-export
Content-Type: multipart/form-data

file=<result.json>
monitor=false          # true — сразу выставить is_monitored=true
```

Ответ:

```json
{
  "telegram_id": -1001234567890,
  "title": "Название чата",
  "messages_parsed": 3420,
  "messages_imported": 3418,
  "messages_skipped": 2,
  "is_monitored": false
}
```

`messages_skipped` — сообщения, которые уже были в БД (дублей не создаётся).

### Что происходит после импорта

Сообщения попадают в `messages` с `classified_at IS NULL` — Processing Engine подберёт их при следующем запуске (этап 3). Если Processing Engine уже работает — сообщения обработаются автоматически в фоне.

Если хочется также включить realtime и backfill для этого чата — после импорта:
```
POST /chats/{telegram_id}/monitor   # требует активного Telegram-соединения
POST /backfill {"telegram_id": ...} # опционально: догрузить пропущенные сообщения через API
```

### Нормализация telegram_id для supergroup/channel

В экспорте Telegram Desktop `id` для супергрупп и каналов — положительное число (например, `1234567890`). В MTProto (и в ReplyRadar) канонический `telegram_id` таких чатов имеет префикс `-100` (например, `-1001234567890`). Парсер добавляет префикс автоматически по полю `type`:

| Тип в экспорте | Нормализация |
|---|---|
| `personal_chat` | ID без изменений |
| `private_group` | ID без изменений (уже отрицательный) |
| `public_supergroup`, `private_supergroup` | `-100` + ID |
| `public_channel`, `private_channel` | `-100` + ID |

Если нормализация дала неверный результат — передать правильный ID явно через параметр `telegram_id_override` (query).

### Формат `result.json` — что поддерживается

| Поле | Обработка |
|---|---|
| `text` — строка | берётся as-is |
| `text` — массив объектов `{type, text}` | конкатенация всех `.text`, форматирование игнорируется |
| `from_id: "user123456789"` | парсится в bigint: `123456789` |
| `from_id: "channel123456789"` | парсится в bigint: `123456789` |
| `from_id` отсутствует | `sender_id = NULL` (анонимный admin группы) |
| `type: "service"` | сообщение пропускается |
| Медиафайлы | игнорируются, текстовая подпись сохраняется |

### Идемпотентность и мерж нескольких экспортов

Два `result.json` одного чата с пересекающимися временными окнами мержатся корректно — уникальный ключ `(chat_id, telegram_msg_id)` гарантирует отсутствие дублей. Повторный импорт того же файла безопасен.

**Оговорка: отредактированные сообщения.** Если сообщение было изменено между двумя экспортами, в БД останется текст из первого импорта — `DO NOTHING` не обновляет уже существующую запись. Это соответствует принципу immutable raw messages: текст сообщения в `messages` не меняется после записи.

### Ограничения

- Максимальный размер `result.json` — 200 МБ (настраивается в `config/default.yaml`: `import.max_file_size_mb`)
- Только текстовые сообщения; вложения, стикеры, голосовые — не хранятся
- Файл загружается в память целиком; для очень больших экспортов (> 200 МБ) используйте backfill

---

## Troubleshooting

**`telegram: not_authorized` после `make auth`**

Проверить `TELEGRAM__SESSION_DIR` в `.env` — должен указывать туда, где лежит `.session` файл.

**Backfill завершился с `error`**

Смотреть `GET /backfill/status` → поле `error`. Частая причина: Telegram FloodWait (слишком много запросов). Telethon обрабатывает его автоматически с задержкой, но при очень больших чатах backfill может занять значительное время.

**Сообщения не появляются в realtime**

Проверить `GET /status` → `telegram: connected`. Если подключён — убедиться что чат добавлен через `POST /chats/{id}/monitor` до получения новых сообщений. Уже существующие сообщения realtime не захватывает — для них нужен backfill.
