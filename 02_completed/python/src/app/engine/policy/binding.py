"""
Policy binding SDK — the `params` contract (ADR-0010 §7.2, spike B10).

`params` is a typed, bounded, validated contract, not an opaque blob:
  - typed + bounded fields (reject wrong type; clamp out-of-range)
  - runtime-bound value domains (valid values = the app's REAL registry, so the engine
    can never propose a value that doesn't exist)
  - cross-field invariants
  - typed read with a FAIL-CLOSED default (missing/invalid/unknown-version -> current behavior)
  - a discovery manifest advertising the action space

Domain schemas live in `policy/domains/` — one module per domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Field:
    type: type
    default: Any
    min: int | float | None = None
    max: int | float | None = None
    enum_ref: str | None = None       # key into value_domains
    is_map_of_enum: bool = False      # dict<str, enum value>


@dataclass
class PolicySchema:
    domain: str
    version: int
    fields: dict[str, Field]
    value_domains: dict[str, set]
    invariants: list[Callable[[dict], str | None]] = field(default_factory=list)

    @property
    def defaults(self) -> dict[str, Any]:
        return {k: (dict(f.default) if isinstance(f.default, dict) else f.default)
                for k, f in self.fields.items()}


@dataclass
class ValidationResult:
    ok: bool
    cleaned: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def validate_and_clamp(schema: PolicySchema, params: dict[str, Any]) -> ValidationResult:
    notes: list[str] = []
    cleaned: dict[str, Any] = {}

    for k in params:
        if k not in schema.fields:
            return ValidationResult(False, notes=[f"reject: unknown field '{k}'"])

    for name, f in schema.fields.items():
        val = params.get(name, f.default)

        if f.is_map_of_enum:
            if not isinstance(val, dict):
                return ValidationResult(False, notes=[f"reject: '{name}' must be a map"])
            domain = schema.value_domains.get(f.enum_ref, set())
            for tier, v in val.items():
                if v not in domain:
                    return ValidationResult(False, notes=[f"reject: '{name}[{tier}]'='{v}' not in '{f.enum_ref}'"])
            cleaned[name] = dict(val)
            continue

        if f.enum_ref:
            if val not in schema.value_domains.get(f.enum_ref, set()):
                return ValidationResult(False, notes=[f"reject: '{name}'='{val}' not in '{f.enum_ref}'"])
            cleaned[name] = val
            continue

        if f.type is bool:  # before int: bool is a subclass of int
            if not isinstance(val, bool):
                return ValidationResult(False, notes=[f"reject: '{name}' must be bool"])
            cleaned[name] = val
            continue

        if f.type in (int, float):
            if not isinstance(val, f.type) or isinstance(val, bool):
                return ValidationResult(False, notes=[f"reject: '{name}' must be {f.type.__name__}"])
            if f.min is not None and val < f.min:
                notes.append(f"clamp {name} {val} -> {f.min}"); val = f.min
            if f.max is not None and val > f.max:
                notes.append(f"clamp {name} {val} -> {f.max}"); val = f.max
            cleaned[name] = val
            continue

        if not isinstance(val, f.type):
            return ValidationResult(False, notes=[f"reject: '{name}' must be {f.type.__name__}"])
        cleaned[name] = val

    for inv in schema.invariants:
        msg = inv(cleaned)
        if msg:
            return ValidationResult(False, notes=[f"reject: invariant — {msg}"])

    return ValidationResult(True, cleaned, notes)


def bind_policy(schema: PolicySchema, active_policy: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    """Typed read with FAIL-CLOSED default. Returns (params, source)."""
    if active_policy is None:
        return schema.defaults, "fail-closed: no active policy -> current behavior"
    if active_policy.get("schema_version") != schema.version:
        return schema.defaults, f"fail-closed: unknown schema_version {active_policy.get('schema_version')}"
    res = validate_and_clamp(schema, active_policy.get("params", {}))
    if not res.ok:
        return schema.defaults, f"fail-closed: invalid params ({res.notes[0]})"
    return res.cleaned, ("ok" if not res.notes else "ok (clamped: " + "; ".join(res.notes) + ")")


def discovery_manifest(schemas: list[PolicySchema]) -> dict[str, Any]:
    """What the app advertises to the engine (its optimizable surface / action space)."""
    return {s.domain: {"schema_version": s.version, "knobs": list(s.fields.keys()),
                       "value_domains": {k: sorted(v) for k, v in s.value_domains.items()}}
            for s in schemas}
