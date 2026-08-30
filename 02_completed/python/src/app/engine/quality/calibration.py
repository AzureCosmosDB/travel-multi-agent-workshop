"""
Judge calibration (ADR-0010 §5.1 / §5.2, spike B9).

A judge is only trustworthy if it agrees with human labels. `calibrate` runs a judge over
a labeled set and reports agreement so "the reference-free judge agrees with the labeled
datasets within tolerance" is a checkable claim, not an assertion.

Labels are pass/fail (the robust, judge-agnostic signal); agreement is the fraction of
examples where `judge.passed == label`, reported alongside precision/recall on the
"pass" class so a judge that trivially passes everything is caught.
"""

from __future__ import annotations

from dataclasses import dataclass

from .judge import EvaluationResult, QualityExample, QualityJudge


@dataclass
class LabeledExample:
    example: QualityExample
    label_pass: bool          # human ground-truth: is this response acceptable?


def calibrate(judge: QualityJudge, dataset: list[LabeledExample], *, tolerance: float = 0.8) -> dict:
    """Run `judge` over labeled data; report agreement + P/R and whether it clears tolerance."""
    n = len(dataset) or 1
    tp = fp = tn = fn = 0
    results: list[EvaluationResult] = []
    for item in dataset:
        res = judge(item.example)
        results.append(res)
        if res.passed and item.label_pass:
            tp += 1
        elif res.passed and not item.label_pass:
            fp += 1
        elif not res.passed and not item.label_pass:
            tn += 1
        else:
            fn += 1
    agreement = (tp + tn) / n
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {
        "n": len(dataset), "agreement": round(agreement, 4),
        "precision": round(precision, 4), "recall": round(recall, 4),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "within_tolerance": agreement >= tolerance,
        "tolerance": tolerance,
    }
