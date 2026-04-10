---
name: Этап 3 завершён
description: Processing Core реализован — LLM client, стадии classify/extract/embed, ProcessingEngine, quarantine, admin API
type: project
---

Processing Core реализован в этапе 3.

**Why:** Чтобы сообщения из таблицы messages проходили LLM-обработку и заполняли commitments/pending_replies/communication_risks.

**Что сделано:**
- `llm/client.py` — LiteLLM wrapper, методы classify/extract/embed/check_health
- `llm/contracts/classify.py`, `extract.py` — Pydantic-схемы ответов LLM
- `llm/prompts/classify.py`, `extract.py` — промпты для LM Studio
- `processing/classify.py`, `extract.py`, `embed.py` — стадии с таксономией ошибок transient/permanent
- `processing/engine.py` — ProcessingEngine с realtime-loop (asyncio.Queue) и backfill-loop, приоритет realtime
- `db/repos/signals.py` — upsert commitments/pending_replies/communication_risks по source_fingerprint
- `db/repos/quarantine.py` — CRUD для processing_quarantine
- `api/routes/admin.py` — GET /admin/quarantine, POST /admin/quarantine/{id}/reprocess|skip
- `bootstrap.py` обновлён — LLMClient и ProcessingEngine создаются при старте
- `GET /status` теперь проверяет LM Studio через `llm.check_health()`

**Архитектурные решения:**
- Все repo-функции принимают `asyncpg.Pool` (не Connection) — следует паттерну существующего кода, обходит PoolConnectionProxy/Connection тип-проблему
- litellm используется с форматом модели `openai/<model_name>` для LM Studio
- Retry-счётчики in-memory (сбрасываются при рестарте — ок для MVP)
- pgvector принимает строку `[x,y,z,...]` с ::vector кастом в SQL

**How to apply:** При работе над этапом 4 (API сценариев) — таблицы commitments/pending_replies/communication_risks уже заполняются после backfill.
