# Observability

Как читать состояние системы через `/status` и `/admin/metrics`.

---

## GET /status — компонентный health check

```json
{
  "telegram": "connected",
  "db": "writable",
  "lm_studio": "reachable",
  "scheduler": "alive",
  "pipeline": {
    "realtime_queue_depth": 0,
    "backlog_classify": 12,
    "backlog_extract": 5,
    "backlog_embed": 5,
    "backlog_entity_extract": 34,
    "quarantine_size": 2
  }
}
```

### Статусы компонентов

| Компонент | Значения | Что означает проблема |
|-----------|----------|-----------------------|
| `telegram` | `connected` / `disconnected` / `reconnecting` | сообщения не поступают, история может теряться |
| `db` | `writable` / `readonly` / `unreachable` | вся система деградирует, ingestion в best-effort |
| `lm_studio` | `reachable` / `unreachable` | обработка приостановлена, backlog растёт |
| `scheduler` | `alive` / `dead` | summaries не обновляются по расписанию |

### Пороги для pipeline

| Метрика | Норма | Внимание | Действие |
|---------|-------|----------|----------|
| `realtime_queue_depth` | 0–5 | > 20 | processing не успевает за realtime |
| `backlog_*` (любая стадия) | 0–50 | > 200 | LM Studio медленный или недоступен |
| `backlog_entity_extract` | выше других | > 500 | нормально для первого backfill, иначе — проблема |
| `quarantine_size` | 0 | > 0 | требует ревью (см. `docs/runbooks/backlog-growing.md`) |

---

## GET /admin/metrics — метрики pipeline

```json
{
  "realtime_lag_p95_seconds": 4.2,
  "backlog_by_stage": {
    "classify": 12,
    "extract": 5,
    "embed": 5,
    "entity_extract": 34
  },
  "llm_parse_error_rate_1h": 0.03,
  "quarantine_size": 2,
  "entity_activation_rate_7d": 0.18,
  "entity_merge_error_rate_30d": 0.04
}
```

### Интерпретация метрик

**`realtime_lag_p95_seconds`**
Время от получения сообщения Telethon до записи `classified_at`. P95 < 10s — норма. Рост означает перегрузку processing engine или недоступность LM Studio.

**`backlog_by_stage`**
Число сообщений с NULL timestamp для каждой стадии. Нормально расти во время backfill. После backfill должен стремиться к нулю. Если растёт в realtime-режиме — processing не справляется.

**`llm_parse_error_rate_1h`**
Доля ответов LLM, не прошедших Pydantic-контракт за последний час. 
- < 0.05 — норма  
- 0.05–0.15 — промпт деградирует или модель сменилась  
- > 0.15 — немедленно проверить LM Studio и версию модели  

Резкий рост после изменения промпта = регрессия, нужны evals.

**`quarantine_size`**
Любое ненулевое значение требует внимания. Сообщения в quarantine не обрабатываются автоматически — нужен ручной reprocess или skip. Процесс: `docs/runbooks/backlog-growing.md`.

**`entity_activation_rate_7d`**
Доля candidate-сущностей, перешедших в active за 7 дней.
- Слишком низкая (< 0.05) — activation policy слишком строгая, полезные сущности не активируются  
- Слишком высокая (> 0.5) — порог слишком мягкий, orphan entities просачиваются  
- Калибровочный диапазон уточняется на реальных данных  

**`entity_merge_error_rate_30d`**
Доля операций unmerge от общего числа merge за 30 дней. Прокси-метрика качества entity resolution.
- < 0.05 — resolution работает хорошо  
- > 0.10 — порог similarity или логика подтверждения требует пересмотра  

---

## Сигналы для немедленного действия

Любой из этих сигналов требует проверки без откладывания:

1. `telegram: disconnected` более 5 минут
2. `db: unreachable` — любая длительность
3. `quarantine_size` > 5 за один день
4. `llm_parse_error_rate_1h` > 0.20
5. `backlog_classify` растёт > 30 минут подряд без уменьшения
6. `entity_merge_error_rate_30d` > 0.15

Для каждого из этих случаев есть runbook в `docs/runbooks/`.
