# Ручные операции с knowledge graph

## Статус документа

Этот документ описывает целевой операторский слой для knowledge graph. В текущей кодовой базе этих API и таблиц ещё нет.

Сейчас из ручных операций реально доступны только действия над `processing_quarantine`:

- `GET /admin/quarantine`
- `POST /admin/quarantine/{id}/reprocess`
- `POST /admin/quarantine/{id}/skip`

## Planned knowledge-graph operations

Ниже перечислены операции, которые планируется добавить после появления knowledge-domain и соответствующего API.

### `activate`

Планируемое действие: перевести сущность из `candidate` в `active`, чтобы она участвовала в поиске, digest и query API.

Планируемый API:

```text
POST /people/{id}/activate
```

### `mute`

Планируемое действие: скрыть сущность из пользовательских поверхностей без удаления фактов.

Планируемый API:

```text
POST /people/{id}/mute
```

### `merge`

Планируемое действие: склеить две сущности, если система раздробила один и тот же объект на несколько профилей.

Планируемый API:

```text
POST /people/{a}/merge/{b}
```

### `unmerge`

Планируемое действие: откатить ошибочный merge по audit trail.

Планируемый API:

```text
POST /people/{id}/unmerge
```

### `relate`

Планируемое действие: вручную добавить связь между двумя сущностями.

Планируемый API:

```text
POST /people/{a}/relate/{b}
```

## Предпосылки для реализации

Чтобы эти операции стали реальными, в проекте должны появиться:

- таблицы `entities`, `entity_facts`, `entity_relations`, `entity_audit_log`
- use cases для command-path knowledge graph
- query API `/people` и `/orgs`
- optimistic locking и audit trail

До этого момента `manual-ops.md` следует читать как design note, а не как runbook по существующему API.
