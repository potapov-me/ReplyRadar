# ReplyRadar

Локальный single-user инструмент для навигации по Telegram-перепискам.

Сейчас репозиторий покрывает ingestion, ручной импорт истории, processing pipeline первого уровня и базовые admin-операции. Knowledge graph, digest, scheduler и scenario API ещё не реализованы.

## Что уже работает

- FastAPI-приложение с lifecycle-инициализацией компонентов
- `GET /status` с состоянием БД, Telegram, LM Studio и backlog pipeline
- `POST /chats/{telegram_id}/monitor` для регистрации чата в realtime-monitoring
- `POST /backfill` и `GET /backfill/status` для загрузки истории и DB-only wakeup
- `POST /import/telegram-export` для импорта `result.json` из Telegram Desktop
- `ProcessingEngine` со стадиями `classify`, `extract`, `embed`
- `processing_quarantine` и admin-роуты `GET /admin/quarantine`, `POST /admin/quarantine/{id}/reprocess|skip`
- CLI-команды `python -m replyradar auth` и `python -m replyradar eval {classify,extract}`

## Что ещё в roadmap

- query API вроде `/today`, `/pending`, `/commitments`, `/risks`
- knowledge graph по людям и организациям
- summarizer и digest delivery
- scheduler и расширенная observability

## Текущий поток данных

```text
Telegram / Telegram Desktop export
        |
        v
   ingestion
   - Telethon listener
   - BackfillRunner
   - result.json import
        |
        v
   Postgres + pgvector
        |
        v
   ProcessingEngine
   - classify
   - extract
   - embed
        |
        v
   signals + quarantine + status/admin API
```

## Быстрый старт

```bash
cp .env.example .env
make install
make db-up
make migrate
make dev
```

API поднимется на `http://localhost:8000`.

Проверка состояния:

```bash
curl http://localhost:8000/status
```

### Переменные окружения

Минимально полезная конфигурация:

```env
DATABASE__URL=postgresql://postgres:postgres@localhost:5432/replyradar
TELEGRAM__API_ID=12345678
TELEGRAM__API_HASH=your_api_hash
```

Если `TELEGRAM__API_ID=0` или сессия не авторизована, приложение всё равно стартует. В таком режиме доступны `GET /status`, импорт экспорта и DB-only обработка backlog.

### Telegram authorisation

```bash
make auth
```

Команда создаёт файл сессии Telethon (`replyradar.session` по умолчанию) в директории из `TELEGRAM__SESSION_DIR`.

### LM Studio

LLM-стадии `classify`, `extract` и `embed` требуют запущенного LM Studio / совместимого OpenAI API endpoint по адресу из `LLM__BASE_URL` и `EMBEDDING__BASE_URL`.

Если LLM недоступен:

- ingestion продолжает принимать сообщения
- `/status` показывает `lm_studio: unreachable`
- backlog растёт и будет обработан после восстановления LLM

## Основные сценарии

### 1. Подключить realtime-monitoring

1. Авторизовать Telegram-сессию: `make auth`
2. Запустить API: `make dev`
3. Добавить чат: `POST /chats/{telegram_id}/monitor`
4. При необходимости догрузить историю: `POST /backfill`

### 2. Импортировать историю без live-соединения

1. Экспортировать чат из Telegram Desktop в JSON
2. Отправить `result.json` на `POST /import/telegram-export`
3. Вызвать `POST /backfill`, чтобы разбудить DB backlog processing

## Команды разработки

```bash
make test
make lint
make typecheck
make security
make eval-classify
make eval-extract
```

## Статус проекта

| Область | Статус | Примечание |
|---|---|---|
| Фундамент | ✓ | `src` layout, config, logging, Alembic, DB pool, `/status` |
| Ingestion | ✓ | listener, monitor, backfill, Telegram Desktop import |
| Processing core | ✓ | classify (batch + fallback), extract (batch upsert), embed, quarantine |
| Admin API | ✓ | quarantine list/reprocess/skip |
| Scenario API | planned | read-модели и `/today`-подобные ручки ещё не добавлены |
| Knowledge graph | planned | в коде пока нет domain/API слоя |
| Digest / summarizer | planned | пакеты-заготовки без runtime-функциональности |
| Scheduler | planned | `/status` возвращает `scheduler: not_started` |

## Документация

- [Обзор документации](./docs/README.md)
- [Архитектура](./docs/architecture.md)
- [Ingestion](./docs/ingestion.md)
- [Observability](./docs/observability.md)
- [Структура проекта](./docs/structure.md)
- [План разработки](./docs/plan.md)
- [Evals](./docs/evals.md)
- [ADR](./docs/adr/README.md)
- [Code review](./docs/review.md)

## Автор

Константин Потапов — разработчик, строит инструменты для личной продуктивности и работы с информацией.

- Сайт: [potapov.me](https://potapov.me)
- Telegram: [@potapov_me](https://t.me/potapov_me)
- Email: [constantin@potapov.me](mailto:constantin@potapov.me)

Если вам интересен проект, есть идеи или хотите поговорить о разработке — пишите.
