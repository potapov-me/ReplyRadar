"""Вычисление бинарных метрик классификации: precision, recall, F1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BinaryMetrics:
    precision: float
    recall: float
    f1: float
    n: int
    tp: int
    fp: int
    fn: int
    tn: int


def compute(predictions: list[bool], labels: list[bool]) -> BinaryMetrics:
    """Вычисляет precision/recall/F1 по спискам предсказаний и меток."""
    if len(predictions) != len(labels):
        raise ValueError(f"длины не совпадают: {len(predictions)} vs {len(labels)}")

    tp = sum(int(p and lbl) for p, lbl in zip(predictions, labels, strict=True))
    fp = sum(int(p and not lbl) for p, lbl in zip(predictions, labels, strict=True))
    fn = sum(int(not p and lbl) for p, lbl in zip(predictions, labels, strict=True))
    tn = sum(int(not p and not lbl) for p, lbl in zip(predictions, labels, strict=True))

    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0

    return BinaryMetrics(
        precision=precision, recall=recall, f1=f1,
        n=len(labels), tp=tp, fp=fp, fn=fn, tn=tn,
    )
