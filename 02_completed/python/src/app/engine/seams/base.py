"""
Seam registry (ADR-0010 §7 — the seam ladder, spike B11).

A **seam** is a safe place the platform is allowed to change: a config policy domain, a
prompt file, or a code recipe. The analyst may only propose changes at a declared seam
(guardrail #1). This registry is the single source of that declared surface — it both
answers "what seams exist?" (`surface()`, consumed by the analyst guardrails) and renders
a concrete **recipe instance** for a chosen seam + params (`render_recipe`).

Adding a seam is the same registry gesture used across the engine — see `catalog.py`.

The seam's *kind* alone determines its risk envelope (apply_mode + autonomy ceiling),
matching `analyst.guardrails`: config applies automatically (reversible, bounded);
prompt/code are staged changes a human attests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..core import Registry

SEAMS = Registry("seams")

# Risk envelope by seam kind — kept in lockstep with analyst.guardrails.
APPLY_MODE = {"config": "auto", "prompt": "staged_change", "code": "staged_change"}
CEILING = {"config": "L4", "prompt": "L3", "code": "L3"}


@dataclass
class Seam:
    """One optimizable seam. `recipe` renders a concrete change instance from params."""
    id: str                                   # unique, e.g. "config:model-selection"
    kind: str                                 # "config" | "prompt" | "code"
    target: str                               # what the analyst card references
    title: str
    description: str
    recipe: Callable[..., dict]               # (seam, params, **ctx) -> change instance
    schema_builder: Callable[..., Any] | None = None  # config seams: build a PolicySchema

    @property
    def apply_mode(self) -> str:
        return APPLY_MODE[self.kind]

    @property
    def ceiling(self) -> str:
        return CEILING[self.kind]


def register(seam: Seam) -> Seam:
    """Register a seam instance (used by the catalog)."""
    SEAMS.register(seam.id)(seam)
    return seam


def get_seam(seam_id: str) -> Seam:
    return SEAMS.get(seam_id)


def list_seams() -> list[Seam]:
    return [s for _id, s in SEAMS.items()]


def find_seam(kind: str, target: str) -> Seam | None:
    """The registered seam matching a (kind, target) pair, or None."""
    for _id, s in SEAMS.items():
        if s.kind == kind and s.target == target:
            return s
    return None


def surface() -> dict[str, set]:
    """The declared optimizable surface, in the exact shape the analyst guardrails expect:
    {"config": {domains}, "prompt": {files}, "code": {recipe ids}}."""
    out: dict[str, set] = {"config": set(), "prompt": set(), "code": set()}
    for _id, s in SEAMS.items():
        out.setdefault(s.kind, set()).add(s.target)
    return out


def render_recipe(seam_id: str, params: dict | None = None, **ctx) -> dict:
    """Render a concrete change instance for a seam + params (the 'recipe instance')."""
    s = SEAMS.get(seam_id)
    return s.recipe(s, params or {}, **ctx)
