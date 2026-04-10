"""Проверяет архитектурные границы импортов между пакетами.

Запускается через pytest, делегирует проверку в lint-imports (import-linter).
Нарушение = упавший тест = блокирующий merge в CI.
"""
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_import_boundaries() -> None:
    cmd = shutil.which("lint-imports")
    assert cmd is not None, "lint-imports не найден в PATH — установи import-linter"
    result = subprocess.run(
        [cmd],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, (
        f"Import boundary violations detected:\n{result.stdout}\n{result.stderr}"
    )
