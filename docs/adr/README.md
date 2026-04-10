# ADR

ADR ведутся в формате записей об архитектурных решениях.

## Правила

- один файл = одно устойчивое решение
- имя: `NNNN-title.md`
- структура: `Статус`, `Контекст`, `Решение`, `Последствия`
- ADR не переписываются задним числом; изменения оформляются новым ADR

## Список решений

- [0001 Local-First и single-user scope](./0001-local-first-single-user-scope.md)
- [0002 PostgreSQL как источник истины](./0002-postgresql-source-of-truth.md)
- [0003 Single-process runtime для MVP](./0003-single-process-runtime-for-mvp.md)
- [0004 Локальный LLM через LM Studio и LiteLLM](./0004-local-llm-via-lm-studio-and-litellm.md)
- [0005 API сценариев и operator-invoked digest](./0005-use-case-api-and-operator-invoked-digest.md)
- [0006 База знаний о людях и организациях](./0006-entity-knowledge-graph.md)
- [0007 Система уверенности для фактов и связей](./0007-entity-confidence-scoring.md)
- [0008 asyncpg и raw SQL вместо SQLAlchemy ORM](./0008-asyncpg-raw-sql.md)
- [0009 Модель активации сущностей для фильтрации orphan entities](./0009-orphan-entity-activation-model.md)
- [0010 Точечное применение тактического DDD в knowledge-домене](./0010-tactical-ddd-in-knowledge-domain.md)
- [0011 Таксономия ошибок и quarantine-путь для LLM-стадий](./0011-error-taxonomy-and-quarantine.md)
- [0012 Audit trail и optimistic locking для ручных операций с knowledge graph](./0012-audit-trail-and-optimistic-locking.md)
- [0013 Разделение command и query путей](./0013-command-query-separation.md)
- [0014 Policy-as-code для доменных эвристик](./0014-policy-as-code.md)
- [0015 Формальные границы импортов между пакетами](./0015-import-boundaries.md)
- [0016 Инструменты статического анализа (ruff, mypy, pyright, bandit)](./0016-static-analysis-toolchain.md)
- [0017 Импорт экспорта Telegram Desktop как резервный путь доступа к истории](./0017-telegram-export-import-as-mtproto-fallback.md)
- [0018 Абсолютные импорты внутри пакета replyradar](./0018-absolute-imports.md)
