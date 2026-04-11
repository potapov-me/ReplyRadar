"""Eval-раннер для стадии Classify.

Загружает evals/datasets/classify/examples.jsonl, вызывает LLM,
сравнивает результаты с baseline. Выходной код 1 при регрессии.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from replyradar.eval.baseline import load as load_baseline
from replyradar.eval.baseline import save as save_baseline
from replyradar.eval.metrics import BinaryMetrics
from replyradar.eval.metrics import compute as compute_metrics

if TYPE_CHECKING:
    from replyradar.llm.client import LLMClient

DATASET = Path("evals/datasets/classify/examples.jsonl")
BASELINE = Path("evals/datasets/classify/baseline.json")

# Допустимое падение метрики относительно baseline
TOLERANCES: dict[str, float] = {"precision": 0.05, "recall": 0.03, "f1": 0.04}


def _load_examples(path: Path) -> list[dict[str, Any]]:
    examples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        examples.append(json.loads(line))
    return examples


async def run(llm: LLMClient, *, update_baseline: bool = False) -> int:
    """Запускает classify eval. Возвращает 0 при успехе, 1 при ошибке или регрессии."""
    if not DATASET.exists():
        print(f"ERROR: датасет не найден: {DATASET}")
        return 1

    examples = _load_examples(DATASET)
    if not examples:
        print("ERROR: датасет пуст — добавьте примеры в evals/datasets/classify/examples.jsonl")
        return 1

    print(f"Classify eval: {len(examples)} примеров\n")

    predictions: list[bool] = []
    labels: list[bool] = []
    errors = 0

    for ex in examples:
        try:
            result = await llm.classify(ex["text"], ex.get("sender"))
            predicted = result.is_signal
            expected = bool(ex["is_signal"])
            predictions.append(predicted)
            labels.append(expected)
            mark = "✓" if predicted == expected else "✗"
            note = f"  # {ex['note']}" if ex.get("note") else ""
            print(
                f"  [{mark}] {ex['id']}: expected={expected} got={predicted}"
                f" conf={result.confidence:.2f}{note}"
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"  [!] {ex['id']}: ERROR {exc}")
            errors += 1

    if errors:
        print(f"\n{errors} ошибок при вызовах LLM — прерываем eval")
        return 1

    m = compute_metrics(predictions, labels)
    _print_metrics(m)

    baseline = load_baseline(BASELINE)

    if update_baseline:
        save_baseline(BASELINE, _to_dict(m))
        print("✓ Baseline обновлён")
        return 0

    if baseline is None:
        print(
            "\nBaseline не найден.\n"
            "Запустите с --update-baseline чтобы зафиксировать текущий результат."
        )
        return 0

    return _check_regression(m, baseline)


# ── helpers ───────────────────────────────────────────────────────────────────


def _print_metrics(m: BinaryMetrics) -> None:
    print(f"\nМетрики classify (n={m.n}):")
    print(f"  Precision : {m.precision:.3f}  (TP={m.tp} FP={m.fp})")
    print(f"  Recall    : {m.recall:.3f}  (TP={m.tp} FN={m.fn})")
    print(f"  F1        : {m.f1:.3f}")
    print(f"  Accuracy  : {(m.tp + m.tn) / m.n:.3f}")


def _to_dict(m: BinaryMetrics) -> dict[str, Any]:
    return {
        "precision": round(m.precision, 4),
        "recall": round(m.recall, 4),
        "f1": round(m.f1, 4),
        "n": m.n,
    }


def _check_regression(m: BinaryMetrics, baseline: dict[str, Any]) -> int:
    failed: list[str] = []
    for metric, tol in TOLERANCES.items():
        current = getattr(m, metric)
        base = float(baseline.get(metric, 0.0))
        if current < base - tol:
            threshold = base - tol
            failed.append(
                f"  {metric:10s}: {current:.3f} < {base:.3f} − {tol:.2f} = {threshold:.3f}"
            )

    if failed:
        print("\n❌ РЕГРЕССИЯ:")
        for line in failed:
            print(line)
        return 1

    print("\n✓ Нет регрессии относительно baseline")
    return 0
