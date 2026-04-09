# ADR-0016: Инструменты статического анализа

## Статус

Принято

## Контекст

Python-проект с asyncio, LLM-интеграцией и нетривиальной доменной логикой. Без статического анализа ошибки типов, небезопасные паттерны и стилевой дрейф накапливаются незаметно. Выбор инструментов влияет на скорость обратной связи и операционную стоимость поддержки.

## Решение

Четыре инструмента с разными ролями, все запускаются в CI на каждый PR.

### Ruff — линтер и форматтер

Заменяет `flake8`, `isort`, `pyupgrade` и `black`. Один инструмент, порядка быстрее.

```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "TCH"]
# E/F — базовые ошибки, I — импорты, UP — pyupgrade,
# B — bugbear (опасные паттерны), SIM — simplification, TCH — type-checking imports
```

Форматирование: `ruff format` (заменяет black).

### Mypy — проверка типов

Строгий режим для `knowledge/` и `db/repos/` где доменные правила и SQL-интерфейсы. Мягкий для остальных модулей на старте.

```toml
[tool.mypy]
python_version = "3.13"
strict = false
warn_return_any = true
warn_unused_ignores = true

[[tool.mypy.overrides]]
module = ["replyradar.knowledge.*", "replyradar.db.repos.*"]
strict = true
```

### Pyright — дополнительная проверка типов

Работает параллельно с mypy. Лучше понимает asyncio и generic-типы. Используется в режиме `basic` для всего проекта; в VSCode/PyCharm даёт inline-подсказки.

```json
// pyrightconfig.json
{
  "pythonVersion": "3.13",
  "typeCheckingMode": "basic",
  "include": ["src"]
}
```

Расхождение mypy и pyright в одном месте — сигнал к ревью типизации, не повод игнорировать один из них.

### Bandit — анализ безопасности

Ищет паттерны типа hardcoded secrets, небезопасный `subprocess`, SQL-инъекции через f-строки.

```toml
[tool.bandit]
exclude_dirs = [".venv", "tests"]
skips = ["B101"]  # assert в тестах — допустимо
```

Уровень `medium` и выше блокирует CI. `low` — предупреждение.

## Порядок запуска в CI

```bash
ruff check src/          # линтер
ruff format --check src/ # форматтер (только проверка, не изменение)
mypy src/
pyright src/
bandit -r src/ -ll       # только medium и выше
```

Локально перед коммитом:

```bash
ruff format src/ && ruff check src/ --fix
```

## Последствия

- Добавляются dev-зависимости: `ruff`, `mypy`, `pyright`, `bandit`.
- `knowledge/` и `db/repos/` имеют более строгую типизацию — это осознанный выбор: domain rules и SQL-интерфейсы требуют точности.
- Новые модули вне `strict`-зоны не обязаны быть полностью типизированы на старте, но постепенно подтягиваются.
- `# type: ignore` и `# noqa` разрешены, но требуют комментария с объяснением.
