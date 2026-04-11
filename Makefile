.PHONY: install dev digest test test-integration lint format typecheck security check \
        db-up db-down db-logs db-reset \
        migrate migration downgrade \
        eval-classify eval-extract eval-classify-update eval-extract-update \
        help

# Цвета для вывода
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
NC     := \033[0m

help: ## Показать это меню помощи
	@echo "$(GREEN)Команды управления$(NC)"
	@echo "=============================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "$(YELLOW)%-25s$(NC) %s\n", $$1, $$2}'

# ── Зависимости ───────────────────────────────────────────────────────────────

install: ## Установить зависимости (включая dev)
	uv sync --extra dev

# ── Разработка ────────────────────────────────────────────────────────────────

dev: ## Запустить API с hot-reload
	uv run uvicorn src.replyradar.main:app --reload

auth: ## Авторизовать Telegram-аккаунт (создать .session файл)
	uv run python -m replyradar auth

digest: ## Запустить CLI дайджест
	uv run python -m replyradar digest

# ── База данных (docker) ──────────────────────────────────────────────────────

db-up: ## Поднять Postgres в Docker
	docker compose up -d postgres

db-down: ## Остановить Docker-контейнеры
	docker compose down

db-logs: ## Следить за логами Postgres
	docker compose logs -f postgres

db-reset: ## Пересоздать БД с нуля (удаляет данные!)
	docker compose down -v
	docker compose up -d postgres

# ── Миграции ─────────────────────────────────────────────────────────────────

migrate: ## Применить миграции (alembic upgrade head)
	uv run alembic upgrade head

migration: ## Создать миграцию: make migration msg="описание"
	uv run alembic revision --autogenerate -m "$(msg)"

downgrade: ## Откатить последнюю миграцию
	uv run alembic downgrade -1

# ── Тесты ────────────────────────────────────────────────────────────────────

test: ## Запустить unit-тесты (без LM Studio)
	uv run pytest -q -m "not integration"

test-integration: ## Запустить integration-тесты с живой LM Studio
	uv run pytest tests/integration/ -v -m integration

# ── Статический анализ ────────────────────────────────────────────────────────

format: ## Форматировать код (ruff format + fix)
	uv run ruff format src/ tests/
	uv run ruff check src/ tests/ --fix

lint: ## Проверить стиль, pylint и границы импортов
	uv run ruff check src/ tests/
	uv run pylint src/
	uv run lint-imports

typecheck: ## Проверить типы (mypy + pyright)
	uv run mypy src/
	uv run pyright src/

security: ## Проверить безопасность (bandit)
	uv run bandit -r src/ -ll

check: format lint typecheck security test ## Полная проверка перед коммитом

# ── Evals ────────────────────────────────────────────────────────────────────

eval-classify: ## Прогнать evals для стадии classify (требует LM Studio)
	uv run python -m replyradar eval classify

eval-extract: ## Прогнать evals для стадии extract (требует LM Studio)
	uv run python -m replyradar eval extract

eval-classify-update: ## Зафиксировать classify baseline (после смены промпта/модели)
	uv run python -m replyradar eval classify --update-baseline

eval-extract-update: ## Зафиксировать extract baseline (после смены промпта/модели)
	uv run python -m replyradar eval extract --update-baseline
