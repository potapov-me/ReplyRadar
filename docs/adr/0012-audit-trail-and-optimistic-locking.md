# ADR-0012: Audit trail и optimistic locking для ручных операций с knowledge graph

## Статус

Принято

## Контекст

Knowledge graph поддерживает ручные операции: activate, mute, merge, unmerge, relate, override fact. Без версионирования записей две одновременные операции (пусть даже в CLI-режиме) могут перезаписать друг друга без предупреждения. Без audit trail непонятно, кто и когда изменил граф — это критично для доверия к данным и отладки неверных merge.

Для single-user MVP race condition маловероятен, но merge/unmerge — деструктивные операции, после которых нужна история.

## Решение

### Optimistic locking

Добавить поле `version int NOT NULL DEFAULT 1` на таблицу `entities`.

При любом UPDATE из operator action:
```sql
UPDATE entities SET ..., version = version + 1
WHERE id = :id AND version = :expected_version
```
Если `rowcount = 0` → ответ `409 Conflict` с текущей версией. Клиент перечитывает и повторяет с актуальной версией.

Применяется к: activate, mute, merge, unmerge, relate.  
Не применяется к: автоматическим обновлениям из EntityExtract (они работают через upsert, не через version check).

### Audit trail

```sql
entity_audit_log
  id            uuid PK
  entity_id     uuid FK → entities   -- NULL если действие затрагивает несколько (merge)
  action        text                 -- 'activate' | 'mute' | 'merge' | 'unmerge' |
                                     -- 'relate' | 'fact_override' | 'auto_activate'
  actor         text                 -- 'user' | 'system'
  version_from  int
  version_to    int
  payload       jsonb                -- snapshot изменений: {before: {...}, after: {...}}
  created_at    timestamptz
```

Запись создаётся в одной транзакции с изменением `entities`. Не удаляется при удалении чата — это операторская история, а не пользовательские данные.

Доступ: `GET /admin/entities/{id}/audit` — хронологический лог всех операций над сущностью.

## Последствия

- Добавляется `version` на `entities` и таблица `entity_audit_log`.
- Все operator-facing мутации возвращают текущую `version` в ответе.
- API принимает `expected_version` в теле запроса для мутаций; отсутствие поля = отказ от проверки (допустимо для автоматических операций).
- Unmerge становится операционально возможным: audit log хранит `payload.before` с состоянием до merge.
- Размер `entity_audit_log` растёт медленно (только ручные операции), retention не требуется.
