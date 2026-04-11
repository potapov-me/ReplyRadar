# Code Review: этап 3

## Findings

1. Medium — batch-классификация в backfill всё ещё меняет семантику `context_window` для большинства исторических сообщений. Раньше backlog шёл через `_process_row()`, где перед classify всегда подтягивались предыдущие сообщения чата (`src/replyradar/processing/engine.py:285`, `src/replyradar/processing/engine.py:292`). Теперь основной batch-путь намеренно работает без контекста (`src/replyradar/processing/engine.py:124`), а контекст восстанавливается только в fallback-пути для сообщений, которые batch-ответ потерял (`src/replyradar/processing/engine.py:338`). Если для проекта важно сохранять прежнюю точность на контекст-зависимых репликах вроде "ок, сделаю" или "жду ответа", это остаётся поведенческой регрессией, а не чистой оптимизацией.

## Assumptions

- ревью выполнено по текущему diff в `config/default.yaml`, `src/replyradar/config.py`, `src/replyradar/llm/client.py`, `src/replyradar/llm/contracts/classify.py`, `src/replyradar/llm/prompts/classify.py`, `src/replyradar/processing/classify.py`, `src/replyradar/processing/engine.py`
- полноценный e2e прогон с живыми Postgres, LM Studio и Telegram в этой сессии не выполнялся

## Checks

- `uv run pytest -q .` проходит
- `python3 -m compileall src tests` проходит

## Residual Risks

- нет тестов, которые покрывают новый batch-путь `classify_batch`: partial-missing items, transient ошибки LiteLLM и осознанную потерю контекста в основном backfill-пути
- стоит отдельно подтвердить end-to-end поведение на реальной БД и живом LLM-контуре: backfill/realtime действительно доводят сообщения до `commitments`, `pending_replies`, `communication_risks`, а batch-classify не деградирует качество на исторических чатах
