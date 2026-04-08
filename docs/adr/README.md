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
