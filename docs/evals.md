# Evals — процесс оценки качества LLM-стадий

Высокоуровневый процесс. Технические детали (формат датасетов, annotation protocol, метрики) — в `evals/README.md`.

---

## Что блокирует merge

Следующие изменения **требуют прогона evals** перед merge:

| Изменение | Стадии для прогона |
|-----------|--------------------|
| Любой файл в `llm/prompts/` | соответствующая стадия |
| Любой файл в `llm/contracts/` | соответствующая стадия |
| `model` или `base_url` в `config/` | все стадии |
| Пороги `confidence.*` в `config/` | extract, entity_extract |
| Пороги `activation.*` в `config/` | entity_extract |

Если метрика упала ниже baseline — PR не мерджится до объяснения причины или восстановления метрики.

---

## Команды

```bash
# Прогнать конкретную стадию
python -m replyradar eval classify
python -m replyradar eval extract
python -m replyradar eval entity_extract

# Зафиксировать текущий результат как новый baseline
python -m replyradar eval classify --update-baseline

# Прогнать все стадии
python -m replyradar eval all
```

Результат сохраняется в `evals/datasets/{stage}/baseline.json`.

---

## Когда обновлять baseline

Baseline обновляется явным действием (`--update-baseline`) только если:
- Метрики улучшились — новый промпт работает лучше
- Изменилась задача стадии — старые метрики измеряют не то
- Добавлены новые примеры в датасет

Baseline не обновляется чтобы "скрыть" регрессию.

---

## Добавление примеров

Новый пример добавляется в датасет когда:
- Система допустила ошибку на реальных данных (regression case)
- Обнаружен новый класс спорных случаев
- Добавляется новый тип факта

Минимальный объём для первого baseline: **15–20 примеров на стадию**.  
Рабочий объём: **30–50 примеров на стадию**.

Протокол разметки и формат — в `evals/README.md`.

---

## Стадии и их приоритет

| Стадия | Датасет | Статус |
|--------|---------|--------|
| Classify | `evals/datasets/classify/` | нужен до Этапа 3 |
| Extract | `evals/datasets/extract/` | нужен до Этапа 3 |
| EntityExtract | `evals/datasets/entity_extract/` | нужен до Этапа 5 |
| Summarize | нет датасета | ручная оценка на реальных данных |
