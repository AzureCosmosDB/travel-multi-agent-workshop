"""
Spike B10 — policy binding SDK / the `params` contract (ADR-0012 B10, guide §7.2).

Proves the params contract is a **typed, bounded, validated** thing — not an opaque
blob — with the safety properties the design claims:

  - typed + bounded schema (reject wrong type / unknown field; clamp out-of-range)
  - runtime-bound value domains (a knob's valid values are the app's REAL deployments,
    so the engine can never propose a model that doesn't exist)
  - cross-field invariants (e.g. default_deployment must be one of the tiers' models)
  - typed read with a FAIL-CLOSED default (missing / invalid / unknown-version policy
    -> the app's hardcoded current behavior, never an arbitrary value)
  - a discovery manifest (the app advertises which domains/knobs it exposes)

Pure stdlib, deterministic. `python b10_policy_binding_sdk.py` (exit 0 = pass).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# The app's REAL runtime value domain (its actual Azure deployments). The engine may
# only ever propose values from here — this is the "runtime-bound value domain".
AVAILABLE_DEPLOYMENTS = {"gpt-5.1", "gpt-5-mini", "gpt-5-nano"}

# The app's hardcoded current behavior (what fail-closed falls back to).
SAFE_DEFAULT = {"enabled": False, "trivial_max_words": 6, "default_deployment": "gpt-5.1", "tiers": {}}

SCHEMA_VERSION = 1


@dataclass
class ValidationResult:
    ok: bool                      # False = hard reject (fail-closed to default)
    cleaned: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def validate_and_clamp(params: dict[str, Any]) -> ValidationResult:
    """Validate model-selection params against the (bounded, runtime-bound) schema."""
    allowed = {"enabled", "trivial_max_words", "default_deployment", "tiers"}
    notes: list[str] = []
    cleaned: dict[str, Any] = {}

    # unknown field -> hard reject
    for k in params:
        if k not in allowed:
            return ValidationResult(False, notes=[f"reject: unknown field '{k}'"])

    # enabled : bool
    enabled = params.get("enabled", SAFE_DEFAULT["enabled"])
    if not isinstance(enabled, bool):
        return ValidationResult(False, notes=["reject: 'enabled' must be bool"])
    cleaned["enabled"] = enabled

    # trivial_max_words : int in [1, 50]  -> CLAMP
    tmw = params.get("trivial_max_words", SAFE_DEFAULT["trivial_max_words"])
    if not isinstance(tmw, int) or isinstance(tmw, bool):
        return ValidationResult(False, notes=["reject: 'trivial_max_words' must be int"])
    lo, hi = 1, 50
    if tmw < lo or tmw > hi:
        clamped = max(lo, min(hi, tmw))
        notes.append(f"clamp trivial_max_words {tmw} -> {clamped} (bounds [{lo},{hi}])")
        tmw = clamped
    cleaned["trivial_max_words"] = tmw

    # default_deployment : enum in runtime domain -> hard reject if unknown
    dd = params.get("default_deployment", SAFE_DEFAULT["default_deployment"])
    if dd not in AVAILABLE_DEPLOYMENTS:
        return ValidationResult(False, notes=[f"reject: default_deployment '{dd}' not a real deployment"])
    cleaned["default_deployment"] = dd

    # tiers : map<tier -> deployment in runtime domain> -> hard reject unknown model
    tiers = params.get("tiers", SAFE_DEFAULT["tiers"])
    if not isinstance(tiers, dict):
        return ValidationResult(False, notes=["reject: 'tiers' must be a map"])
    for tier, model in tiers.items():
        if model not in AVAILABLE_DEPLOYMENTS:
            return ValidationResult(False, notes=[f"reject: tier '{tier}' -> '{model}' is not a real deployment"])
    cleaned["tiers"] = dict(tiers)

    # cross-field invariant: default_deployment must appear among the tiers (if tiers set)
    if tiers and dd not in tiers.values():
        return ValidationResult(False, notes=[f"reject: invariant — default_deployment '{dd}' not in tiers {list(tiers.values())}"])

    return ValidationResult(True, cleaned, notes)


def bind_policy(active_policy: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    """Typed read with FAIL-CLOSED default. Returns (params, source)."""
    if active_policy is None:
        return dict(SAFE_DEFAULT), "fail-closed: no active policy -> current behavior"
    if active_policy.get("schema_version") != SCHEMA_VERSION:
        return dict(SAFE_DEFAULT), f"fail-closed: unknown schema_version {active_policy.get('schema_version')}"
    res = validate_and_clamp(active_policy.get("params", {}))
    if not res.ok:
        return dict(SAFE_DEFAULT), f"fail-closed: invalid params ({res.notes[0]})"
    return res.cleaned, ("ok" if not res.notes else "ok (clamped: " + "; ".join(res.notes) + ")")


def discovery_manifest() -> dict[str, Any]:
    """What the app advertises to the engine (the action space)."""
    return {"model-selection": {"schema_version": SCHEMA_VERSION,
                                "knobs": ["enabled", "trivial_max_words", "default_deployment", "tiers"],
                                "value_domain": {"deployments": sorted(AVAILABLE_DEPLOYMENTS)}}}


def run() -> bool:
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail):
        results.append((name, cond, detail))

    # 1. valid params -> accepted, typed read returns them
    good = {"schema_version": 1, "params": {"enabled": True, "trivial_max_words": 6,
            "default_deployment": "gpt-5-mini", "tiers": {"trivial": "gpt-5-nano", "routine": "gpt-5-mini"}}}
    p, src = bind_policy(good)
    check("valid policy accepted", "ok" in src and p["default_deployment"] == "gpt-5-mini", f"src={src}")

    # 2. out-of-range clamped
    clamp = {"schema_version": 1, "params": {"trivial_max_words": 999, "default_deployment": "gpt-5.1"}}
    p, src = bind_policy(clamp)
    check("out-of-range clamped to bound", p["trivial_max_words"] == 50 and "clamp" in src, f"tmw={p['trivial_max_words']}, src={src}")

    # 3. unknown deployment (engine can't propose a nonexistent model) -> fail-closed
    bad_model = {"schema_version": 1, "params": {"default_deployment": "gpt-6-ultra"}}
    p, src = bind_policy(bad_model)
    check("unknown model rejected -> fail-closed to default", p == SAFE_DEFAULT and "fail-closed" in src, src)

    # 4. missing policy -> fail-closed to current behavior
    p, src = bind_policy(None)
    check("missing policy -> fail-closed (current behavior)", p == SAFE_DEFAULT and "no active policy" in src, src)

    # 5. unknown schema version -> fail-closed
    p, src = bind_policy({"schema_version": 99, "params": {"enabled": True}})
    check("unknown schema_version -> fail-closed", p == SAFE_DEFAULT and "schema_version" in src, src)

    # 6. cross-field invariant violation -> fail-closed
    inv = {"schema_version": 1, "params": {"default_deployment": "gpt-5.1", "tiers": {"trivial": "gpt-5-nano"}}}
    p, src = bind_policy(inv)
    check("cross-field invariant enforced", p == SAFE_DEFAULT and "invariant" in src, src)

    # 7. discovery manifest advertises the action space
    man = discovery_manifest()
    check("discovery manifest lists domain + runtime value domain",
          "model-selection" in man and "gpt-5.1" in man["model-selection"]["value_domain"]["deployments"],
          str(man["model-selection"]["value_domain"]))

    print("=" * 78)
    print("B10 — policy binding SDK / params contract")
    print("=" * 78)
    all_pass = True
    for name, ok, detail in results:
        all_pass = all_pass and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    print("-" * 78)
    print(f"  RESULT: {'ALL PASS - params is a typed, bounded, fail-closed contract' if all_pass else 'FAILURES'}")
    print("=" * 78)
    return all_pass


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
