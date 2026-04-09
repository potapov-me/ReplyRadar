# Инварианты данных

Правила, которые система обязана соблюдать всегда. Нарушение — баг, не edge case.

Инварианты проверяются в юнит-тестах `knowledge/` и в интеграционных тестах `tests/`.

---

## Сущности (entities)

**I-1.** Сущность со статусом `active` не может исчезнуть из поиска без явной операции `mute` или `merge`.

**I-2.** Поле `version` монотонно возрастает. Никакая операция не уменьшает `version`.

**I-3.** При `activated_by = 'auto'` должно выполняться хотя бы одно из условий activation policy: прямое участие в чате, вовлечённость в commitments/pending_replies, `mention_count ≥ 3` из `chat_count ≥ 2`.

**I-4.** Поглощённая при merge сущность не возвращается в поиске и не участвует в транзитивных запросах.

**I-5.** `mention_count` совпадает с числом уникальных `message_id` в `entity_fact_sources` и `entity_relation_sources` для данной сущности.

---

## Факты (entity_facts)

**I-6.** Факт с непустым `superseded_by` не считается текущим. При запросе активных фактов сущности `WHERE superseded_by IS NULL`.

**I-7.** Два факта не могут иметь одинаковый `source_fingerprint`. Повторная обработка того же сообщения не создаёт дубля.

**I-8.** `corroboration_count` совпадает с числом строк в `entity_fact_sources` для данного `fact_id`.

**I-9.** Факт не может одновременно быть `superseded_by != NULL` и иметь ненулевой `contradiction_count` без соответствующей записи в `entity_fact_sources`.

---

## Связи (entity_relations)

**I-10.** Связь с `is_directional = false` может быть найдена запросом в любую сторону: `entity_a → entity_b` и `entity_b → entity_a`.

**I-11.** Уверенность по транзитивной цепочке не превышает минимальной `base_confidence` среди рёбер цепочки. (Перемножение не повышает уверенность выше самого слабого звена.)

**I-12.** `corroboration_count` связи совпадает с числом строк в `entity_relation_sources` для данного `relation_id`.

---

## Обработка сообщений (processing)

**I-13.** Сообщение с `classified_at IS NULL` не попадает в Extract, Embed или EntityExtract.

**I-14.** Сообщение с `is_signal = false` не попадает в Extract.

**I-15.** Сообщение в `processing_quarantine` не участвует в обычном backfill-цикле. Обработка только через явный `reprocess` или `skip`.

**I-16.** `INSERT ... ON CONFLICT (chat_id, telegram_msg_id) DO NOTHING` — одно Telegram-сообщение = максимум одна строка в `messages`.

---

## Audit trail

**I-17.** Каждая ручная операция (`activate`, `mute`, `merge`, `unmerge`, `relate`, `fact_override`) создаёт запись в `entity_audit_log` в той же транзакции.

**I-18.** Записи `entity_audit_log` не удаляются при удалении чата или сущности.

**I-19.** `version_to` в audit log совпадает с `version` в `entities` после операции.

---

## Как проверять

Инварианты I-1, I-6, I-7, I-13–I-16 проверяются юнит-тестами в `tests/knowledge/` и `tests/processing/`.

Инварианты I-3, I-5, I-8, I-12 проверяются SQL-запросами при необходимости:

```sql
-- Проверка I-5: mention_count расходится с реальным числом источников
SELECT e.id, e.canonical_name, e.mention_count,
       COUNT(DISTINCT s.message_id) AS real_count
FROM entities e
LEFT JOIN entity_fact_sources s ON s.fact_id IN (
    SELECT id FROM entity_facts WHERE entity_id = e.id
)
GROUP BY e.id
HAVING e.mention_count != COUNT(DISTINCT s.message_id);

-- Проверка I-6: активные факты без superseded_by
SELECT COUNT(*) FROM entity_facts
WHERE superseded_by IS NOT NULL
  AND id IN (SELECT fact_id FROM entity_fact_sources); -- используются как текущие
```
