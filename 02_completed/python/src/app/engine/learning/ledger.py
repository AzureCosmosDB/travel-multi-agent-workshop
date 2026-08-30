"""
Outcome ledger + feedback-as-evidence (ADR-0010 §9.2, spike B15).

The system learns 'what works' WITHOUT fine-tuning: record predicted-vs-actual-vs-verdict
per recommendation *pattern*; then (a) re-rank candidates by track record and (b)
calibrate future projections by the observed actual/predicted ratio.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LedgerEntry:
    pattern: str            # e.g. "model-selection", "tool-dedup"
    predicted: float
    actual: float
    verdict: str            # "kept" | "reverted"


def track_record(ledger: list[LedgerEntry], pattern: str) -> dict:
    rows = [e for e in ledger if e.pattern == pattern]
    if not rows:
        return {"n": 0, "realized_ratio": 1.0, "revert_rate": 0.0}   # neutral prior
    realized = sum(e.actual for e in rows) / sum(e.predicted for e in rows)
    revert_rate = sum(1 for e in rows if e.verdict == "reverted") / len(rows)
    return {"n": len(rows), "realized_ratio": realized, "revert_rate": revert_rate}


def calibrated_projection(ledger: list[LedgerEntry], pattern: str, predicted: float) -> float:
    """Correct a raw prediction by the pattern's historical realized ratio."""
    return round(predicted * track_record(ledger, pattern)["realized_ratio"], 4)


def rank_candidates(ledger: list[LedgerEntry], candidates: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """candidates: (pattern, predicted). Score = calibrated saving * reliability. Desc."""
    scored = []
    for pattern, predicted in candidates:
        tr = track_record(ledger, pattern)
        score = predicted * tr["realized_ratio"] * (1.0 - tr["revert_rate"])
        scored.append((pattern, round(score, 4)))
    return sorted(scored, key=lambda x: -x[1])
