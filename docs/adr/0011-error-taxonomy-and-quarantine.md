# ADR-0011: Таксономия ошибок и quarantine-путь для LLM-стадий

## Статус

Принято

## Контекст

Текущая модель обработки ошибок: `*_error` поле + retry при следующем запуске. Это работает для transient сбоев, но не разделяет случаи когда нужно ждать (сеть упала) и когда ручное вмешательство неизбежно (LLM вернул невалидный JSON десять раз подряд). Без этого разделения "идемпотентный retry" превращается в бесконечный цикл шума, а операционной управляемости нет.

## Решение

### Таксономия ошибок

Три класса ошибок с разной политикой:

| Класс | Примеры | Политика |
|-------|---------|----------|
| **transient** | LLM timeout, сеть недоступна, Postgres connection reset | retry с экспоненциальным backoff, `*_error` очищается при успехе |
| **permanent** | ответ LLM не прошёл Pydantic-контракт, сообщение нечитаемо, токен-лимит превышен | quarantine после N неудачных попыток |
| **degraded** | LLM вернул частичный результат (часть полей NULL), low-confidence extraction | записывается с пометкой, обрабатывается, флагуется для ревью |

Поле `*_error` сохраняет класс ошибки: `transient:timeout`, `permanent:schema_validation`, `degraded:low_confidence`.

### Quarantine path

После `MAX_RETRIES` (конфиг, default 3) transient-ошибок или при первом permanent — сообщение перемещается в quarantine:

```sql
processing_quarantine
  id              uuid PK
  message_id      bigint FK → messages
  stage           text        -- 'classify' | 'extract' | 'embed' | 'entity_extract'
  error_class     text        -- 'transient' | 'permanent'
  error_detail    text        -- stacktrace или описание
  raw_llm_response text       -- сырой ответ LLM, не прошедший контракт
  retry_count     int
  quarantined_at  timestamptz
  reviewed_at     timestamptz
  resolution      text        -- 'reprocessed' | 'skipped' | 'fixed_manually'
```

Сообщение в quarantine не участвует в обычном backfill-цикле. Обрабатывается только через явный operator action: `POST /admin/quarantine/{id}/reprocess` или `POST /admin/quarantine/{id}/skip`.

### Метрика управляемости

Размер quarantine — операционная метрика первого уровня. Рост quarantine = сигнал к ревью промптов или контрактов.

## Последствия

- Добавляется таблица `processing_quarantine` и admin-эндпоинты.
- `MAX_RETRIES` и классификатор ошибок — конфигурируемы (см. ADR-0014).
- Runbook для quarantine review добавляется в `docs/runbooks/`.
- Идемпотентный retry не деградирует в бесконечный цикл на broken input.
