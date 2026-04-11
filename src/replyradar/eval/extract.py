"""Eval-раннер для стадии Extract.

Метрика presence-based: считаем TP/FP/FN на уровне «обнаружена ли категория»,
не на уровне точного совпадения полей. Это устойчиво к перефразировкам модели.
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

DATASET = Path("evals/datasets/extract/examples.jsonl")
BASELINE = Path("evals/datasets/extract/baseline.json")

# Допустимое падение метрики относительно baseline
TOLERANCES: dict[str, float] = {
    "commitment_recall": 0.05,
    "commitment_precision": 0.05,
    "pending_reply_recall": 0.05,
    "pending_reply_precision": 0.07,
    "risk_recall": 0.10,
}

_CATEGORIES = ("commitments", "pending_replies", "communication_risks")


def _load_examples(path: Path) -> list[dict[str, Any]]:
    examples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        examples.append(json.loads(line))
    return examples


async def run(llm: LLMClient, *, update_baseline: bool = False) -> int:
    """Запускает extract eval. Возвращает 0 при успехе, 1 при ошибке или регрессии."""
    if not DATASET.exists():
        print(f"ERROR: датасет не найден: {DATASET}")
        return 1

    examples = _load_examples(DATASET)
    if not examples:
        print("ERROR: датасет пуст — добавьте примеры в evals/datasets/extract/examples.jsonl")
        return 1

    print(f"Extract eval: {len(examples)} примеров\n")

    # Для каждой категории: parallel lists (predicted_has, expected_has)
    preds: dict[str, list[bool]] = {c: [] for c in _CATEGORIES}
    labels: dict[str, list[bool]] = {c: [] for c in _CATEGORIES}
    errors = 0

    for ex in examples:
        expected = ex["expected"]
        try:
            result = await llm.extract(ex["text"], ex.get("sender"))
            predicted_counts: dict[str, int] = {
                "commitments": len(result.commitments),
                "pending_replies": len(result.pending_replies),
                "communication_risks": len(result.communication_risks),
            }

            row_marks: list[str] = []
            for cat in _CATEGORIES:
                exp_has = len(expected[cat]) > 0
                got_has = predicted_counts[cat] > 0
                labels[cat].append(exp_has)
                preds[cat].append(got_has)
                if exp_has == got_has:
                    row_marks.append(f"✓{cat[:3]}")
                elif exp_has and not got_has:
                    row_marks.append(f"✗{cat[:3]}(miss)")
                else:
                    row_marks.append(f"✗{cat[:3]}(fp)")

            print(f"  {ex['id']}: {' '.join(row_marks)}")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"  [!] {ex['id']}: ERROR {exc}")
            errors += 1

    if errors:
        print(f"\n{errors} ошибок при вызовах LLM — прерываем eval")
        return 1

    metrics: dict[str, BinaryMetrics] = {}
    for cat in _CATEGORIES:
        metrics[cat] = compute_metrics(preds[cat], labels[cat])

    _print_metrics(metrics)

    flat = _flatten_metrics(metrics)
    baseline = load_baseline(BASELINE)

    if update_baseline:
        save_baseline(BASELINE, flat)
        print("✓ Baseline обновлён")
        return 0

    if baseline is None:
        print(
            "\nBaseline не найден.\n"
            "Запустите с --update-baseline чтобы зафиксировать текущий результат."
        )
        return 0

    return _check_regression(flat, baseline)


# ── helpers ───────────────────────────────────────────────────────────────────

_CAT_LABELS = {
    "commitments": "Commitments",
    "pending_replies": "Pending replies",
    "communication_risks": "Risks",
}


def _print_metrics(metrics: dict[str, BinaryMetrics]) -> None:
    print("\nМетрики extract (presence-based):")
    for cat, m in metrics.items():
        label = _CAT_LABELS[cat]
        print(f"  {label:20s} precision={m.precision:.3f}  recall={m.recall:.3f}  (n={m.n})")


def _flatten_metrics(metrics: dict[str, BinaryMetrics]) -> dict[str, Any]:
    return {
        "commitment_precision": round(metrics["commitments"].precision, 4),
        "commitment_recall": round(metrics["commitments"].recall, 4),
        "pending_reply_precision": round(metrics["pending_replies"].precision, 4),
        "pending_reply_recall": round(metrics["pending_replies"].recall, 4),
        "risk_recall": round(metrics["communication_risks"].recall, 4),
        "n": metrics["commitments"].n,
    }


def _check_regression(flat: dict[str, Any], baseline: dict[str, Any]) -> int:
    failed: list[str] = []
    for metric, tol in TOLERANCES.items():
        current = float(flat.get(metric, 0.0))
        base = float(baseline.get(metric, 0.0))
        if current < base - tol:
            threshold = base - tol
            failed.append(
                f"  {metric:30s}: {current:.3f} < {base:.3f} − {tol:.2f} = {threshold:.3f}"
            )

    if failed:
        print("\n❌ РЕГРЕССИЯ:")
        for line in failed:
            print(line)
        return 1

    print("\n✓ Нет регрессии относительно baseline")
    return 0
