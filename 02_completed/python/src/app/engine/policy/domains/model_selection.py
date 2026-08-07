"""The `model-selection` policy domain."""

from __future__ import annotations

from . import DOMAINS
from ..binding import Field, PolicySchema


def _default_in_tiers(p: dict) -> str | None:
    complexity_tiers = p.get("complexity_tiers") or {}
    if complexity_tiers and p.get("default_deployment") not in complexity_tiers.values():
        return f"default_deployment '{p.get('default_deployment')}' not in complexity_tiers {list(complexity_tiers.values())}"
    return None


@DOMAINS.register("model-selection")
def build(available_deployments, default_deployment: str = "gpt-5.1", **_ctx) -> PolicySchema:
    return PolicySchema(
        domain="model-selection",
        version=1,
        fields={
            "enabled": Field(bool, False),
            "trivial_max_words": Field(int, 6, min=1, max=50),
            "default_deployment": Field(str, default_deployment, enum_ref="deployments"),
            "complexity_tiers": Field(dict, {}, enum_ref="deployments", is_map_of_enum=True),
        },
        value_domains={"deployments": set(available_deployments)},
        invariants=[_default_in_tiers],
    )
