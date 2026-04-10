"""Проверяет архитектурные границы импортов между пакетами.

Запускается через pytest, делегирует проверку в lint-imports (import-linter).
Нарушение = упавший тест = блокирующий merge в CI.
"""

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def _find_lint_imports() -> str | None:
    # 1. Рядом с текущим Python (venv/bin) — работает при `uv run pytest`
    candidate = Path(sys.executable).parent / "lint-imports"
    if candidate.exists():
        return str(candidate)
    # 2. В PATH — работает при активированном venv в CI
    return shutil.which("lint-imports")


def test_import_boundaries() -> None:
    cmd = _find_lint_imports()
    assert cmd is not None, "lint-imports не найден. Установи зависимости: uv sync --extra dev"
    result = subprocess.run(
        [cmd],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, (
        f"Import boundary violations detected:\n{result.stdout}\n{result.stderr}"
    )
