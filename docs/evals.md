# Evals

Высокоуровневые правила для LLM-evals. Технические детали по датасетам и метрикам лежат в [evals/README.md](../evals/README.md).

## Что есть сейчас

В текущем CLI поддерживаются только две стадии:

- `classify`
- `extract`

Команды:

```bash
make eval-classify
make eval-extract

uv run python -m replyradar eval classify
uv run python -m replyradar eval extract
```

Обновление baseline:

```bash
uv run python -m replyradar eval classify --update-baseline
uv run python -m replyradar eval extract --update-baseline
```

## Когда прогон обязателен

Evals нужно запускать перед merge, если меняется что-то из:

- `src/replyradar/llm/prompts/*`
- `src/replyradar/llm/contracts/*`
- модель или endpoint в `config/default.yaml` / `.env`
- логика в `llm/client.py`, влияющая на формат или разбор ответа

## Что считается регрессией

Если метрики падают ниже зафиксированного baseline, изменение нельзя считать безопасным без отдельного объяснения причины.

Цель evals здесь практическая: ловить регрессии на реальных примерах, а не строить полную benchmark-систему.

## Что пока не реализовано

Следующее пока описывает roadmap, а не текущий CLI:

- `entity_extract` eval
- `eval all`
- summarization evals

Если эти команды появятся, документ нужно будет расширить вместе с runtime-изменением.
