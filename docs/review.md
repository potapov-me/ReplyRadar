# Code Review: этап 2

## Findings

### 1. `POST /chats/{id}/monitor` всё ещё может создать мониторинг для невалидного `telegram_id`, если listener не в состоянии `connected`

Проверка существования чата теперь есть, но она срабатывает только когда listener уже подключён. В любом другом состоянии `resolve_chat()` возвращает `None`, после чего роут всё равно создаёт запись в `chats` и выставляет `is_monitored = true`.

- `src/replyradar/api/routes/chats.py:21-37`
- `src/replyradar/ingestion/listener.py:97-109`
- `src/replyradar/usecases/chats.py:17-28`

Почему это важно:
- в состоянии `not_authorized`, `error` или при отключённом Telegram-конфиге API позволяет "успешно" начать мониторинг чата, существование которого не подтверждено
- дальше пользователь получает отложенную ошибку только на `/backfill`, а в БД остаётся ложная monitored-запись

Что исправить:
- для `POST /chats/{id}/monitor` требовать доступный Telegram client и валидировать `telegram_id` всегда
- либо явно возвращать `503/409`, если Telegram сейчас не может подтвердить сущность, вместо silent fallback в режим "доверяем ID"

## Assumptions

- ревью выполнено по требованиям этапа 2 из `docs/plan.md`
- полноценный e2e прогон с живыми Telegram и Postgres в этой сессии не выполнялся

## Checks

- `uv run pytest -q .` проходит
- `python3 -m compileall src tests` проходит
