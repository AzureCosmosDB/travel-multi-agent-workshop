"""
Spike B15 — outcome ledger + feedback-as-evidence (ADR-0012 B15, guide §9.2).

Proves the system "learns what works" WITHOUT fine-tuning: an outcome ledger records
predicted-vs-actual-vs-verdict per recommendation *pattern*, and on the next run the
engine (a) re-ranks candidates by track record and (b) calibrates future projections by
the observed actual/predicted ratio.

Pure stdlib, deterministic. `python b15_outcome_ledger.py` (exit 0 = pass).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LedgerEntry:
    pattern: str            # e.g. "model-selection", "tool-dedup"
    predicted: float
    actual: float
    verdict: str            # "kept" | "reverted"


# Historical outcomes (the growing ledger).
LEDGER = [
    # model-selection: reliably delivered ~ as predicted, never reverted
    LedgerEntry("model-selection", 100, 98, "kept"),
    LedgerEntry("model-selection", 100, 102, "kept"),
    LedgerEntry("model-selection", 100, 100, "kept"),
    # tool-dedup: under-delivered and often reverted
    LedgerEntry("tool-dedup", 100, 30, "reverted"),
    LedgerEntry("tool-dedup", 100, 20, "reverted"),
    LedgerEntry("tool-dedup", 100, 40, "kept"),
]


def track_record(ledger, pattern):
    rows = [e for e in ledger if e.pattern == pattern]
    if not rows:
        return {"n": 0, "realized_ratio": 1.0, "revert_rate": 0.0}  # neutral prior
    realized = sum(e.actual for e in rows) / sum(e.predicted for e in rows)
    revert_rate = sum(1 for e in rows if e.verdict == "reverted") / len(rows)
    return {"n": len(rows), "realized_ratio": realized, "revert_rate": revert_rate}


def calibrated_projection(ledger, pattern, predicted):
    """Deterministic calibration: correct the raw prediction by the pattern's history."""
    return round(predicted * track_record(ledger, pattern)["realized_ratio"], 4)


def rank_candidates(ledger, candidates):
    """candidates: list of (pattern, predicted). Score by calibrated saving * reliability."""
    scored = []
    for pattern, predicted in candidates:
        tr = track_record(ledger, pattern)
        reliability = 1.0 - tr["revert_rate"]
        score = predicted * tr["realized_ratio"] * reliability
        scored.append((pattern, round(score, 4)))
    return sorted(scored, key=lambda x: -x[1])


def run() -> bool:
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail):
        results.append((name, cond, detail))

    # 1. Equal RAW prediction, different track record -> reliable pattern ranks first.
    ranked = rank_candidates(LEDGER, [("model-selection", 100), ("tool-dedup", 100)])
    check("equal predicted -> better track record ranks first",
          ranked[0][0] == "model-selection" and ranked[0][1] > ranked[1][1],
          f"ranked={ranked}")

    # 2. Deterministic calibration halves an over-optimistic prediction.
    proj = calibrated_projection(LEDGER, "tool-dedup", 100)
    tr = track_record(LEDGER, "tool-dedup")
    check("calibration corrects prediction toward realized ratio",
          abs(proj - 100 * tr["realized_ratio"]) < 1e-6 and proj < 100,
          f"tool-dedup projection {proj} (realized ratio {round(tr['realized_ratio'],3)})")

    # 3. A brand-new pattern (no history) uses the neutral prior (predicted as-is).
    proj_new = calibrated_projection(LEDGER, "memory-salience", 100)
    check("new pattern uses neutral prior (no penalty, no boost)", proj_new == 100.0,
          f"new pattern projection {proj_new}")

    # 4. High revert-rate pattern is down-ranked even vs a lower raw prediction.
    ranked2 = rank_candidates(LEDGER, [("model-selection", 60), ("tool-dedup", 100)])
    check("high-revert pattern down-ranked below a lower but reliable prediction",
          ranked2[0][0] == "model-selection",
          f"ranked={ranked2}")

    print("=" * 78)
    print("B15 — outcome ledger + feedback-as-evidence")
    print("=" * 78)
    all_pass = True
    for name, ok, detail in results:
        all_pass = all_pass and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    print("-" * 78)
    print(f"  RESULT: {'ALL PASS - system re-ranks + calibrates from outcomes (no fine-tuning)' if all_pass else 'FAILURES'}")
    print("=" * 78)
    return all_pass


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
