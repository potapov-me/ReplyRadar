# ADR-0014: Policy-as-code для доменных эвристик

## Статус

Принято

## Контекст

Несколько ключевых параметров системы сейчас зафиксированы только в документации или в prose-комментариях в коде: порог активации сущностей (3/2), пороги уверенности (0.75/0.40), порог entity resolution (0.85), период полураспада confidence (365 дней), размер батча EntityExtract, MAX_RETRIES для quarantine. Смена любого из них требует поиска по коду без гарантии, что найдено всё.

## Решение

Все доменные эвристики хранятся в `config/default.yaml` под явными секциями. Читаются через `config.py` (pydantic-settings). Код использует только именованные константы из config — не литералы.

```yaml
# config/default.yaml

activation:
  min_mentions: 3
  min_chats: 2

confidence:
  display_threshold: 0.75    # факт показывается без оговорок
  hedged_threshold: 0.40     # факт показывается с пометкой "вероятно"
  source_weights:
    self: 1.0
    other: 0.7
    inferred: 0.5
  half_life_days: 365
  max_corroboration_boost: 0.40
  corroboration_step: 0.10
  contradiction_penalty_factor: 0.5

entity_resolution:
  similarity_threshold: 0.85

processing:
  backfill_batch_size: 20
  entity_extract_batch_size: 15
  max_retries_before_quarantine: 3
  backfill_concurrency: 1

llm:
  base_url: http://host.docker.internal:1234/v1
  model: local-model
  api_key: lm-studio

embedding:
  provider: lmstudio
  model: text-embedding-nomic-embed-text-v1.5
  base_url: http://host.docker.internal:1234/v1
```

Переменные окружения переопределяют значения по умолчанию (через pydantic-settings). Это позволяет менять пороги без пересборки образа.

### Версионирование политик

Поля `prompt_version` в БД (уже есть) расширяются аналогичным принципом: при изменении доменной эвристики, влияющей на интерпретацию данных, в `evals/` фиксируется baseline результат до и после изменения.

## Последствия

- Единственное место для смены любого числового порога.
- Смена порога активации или confidence не требует grep по кодовой базе.
- Config читается один раз при старте; hot-reload не предусмотрен (требует перезапуска).
- `evals/` становится gate для изменений policy: merge без прогона baseline — нарушение процесса.
