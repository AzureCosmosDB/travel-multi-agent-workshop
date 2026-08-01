"""
Built-in seam catalog (ADR-0010 §7, spike B11).

Registers the seams the reference app exposes — one config domain, two prompt files, one
code recipe — each with a recipe renderer. Mirrors the surface the pipeline declares. Add
a seam by appending a `register(Seam(...))` here (or from your own module).
"""

from __future__ import annotations

from ..policy import DOMAINS, bind_policy
from .base import Seam, register

# Deployments the model-selection schema validates against (reference default; in
# production this comes from the Configuration container).
_DEFAULT_DEPLOYMENTS = {"gpt-5.1", "gpt-5-mini", "gpt-5-nano"}


def _config_recipe(seam: Seam, params: dict, *, available_deployments=None, **_) -> dict:
    """Bind params through the domain's binding SDK → a fail-closed policy document."""
    schema = seam.schema_builder(available_deployments or _DEFAULT_DEPLOYMENTS)
    bound, status = bind_policy(schema, {"schema_version": 1, "params": params})
    # `accepted` = the PROPOSED params bound cleanly (status "ok..."); on fail-closed the
    # SDK returns safe defaults, but the proposal itself was rejected → no policy doc.
    accepted = status.startswith("ok")
    return {
        "seam": seam.id, "kind": seam.kind, "target": seam.target,
        "apply_mode": seam.apply_mode, "autonomy_ceiling": seam.ceiling,
        "status": status, "accepted": accepted,
        "policy_doc": ({"scenario": seam.target, "schema_version": 1, "params": bound}
                       if accepted else None),
    }


def _prompt_recipe(seam: Seam, params: dict, **_) -> dict:
    """Render a staged prompt edit instruction (human-attested; never auto-applied)."""
    guidance = params.get("guidance", "<edit guidance>")
    return {
        "seam": seam.id, "kind": seam.kind, "target": seam.target,
        "apply_mode": seam.apply_mode, "autonomy_ceiling": seam.ceiling,
        "edit": f"Edit prompts/{seam.target}: {guidance}",
        "requires": "human attestation (staged change; regenerate a sample + re-measure)",
    }


def _code_recipe(seam: Seam, params: dict, **_) -> dict:
    """Render a staged code recipe (human reviews the diff; never auto-applied)."""
    return {
        "seam": seam.id, "kind": seam.kind, "target": seam.target,
        "apply_mode": seam.apply_mode, "autonomy_ceiling": seam.ceiling,
        "recipe": seam.target,
        "steps": params.get("steps") or [
            "retrieve the change site via the code-context provider",
            "draft the diff from the retrieved context",
            "stage the diff for human review (no auto-apply)",
        ],
        "requires": "human review of the staged diff",
    }


register(Seam(
    id="config:model-selection", kind="config", target="model-selection",
    title="Per-turn model selection",
    description="Route low realized-complexity turns to a cheaper deployment (auto, reversible).",
    recipe=_config_recipe,
    schema_builder=lambda deps: DOMAINS.get("model-selection")(available_deployments=deps),
))

register(Seam(
    id="prompt:supervisor", kind="prompt", target="supervisor.prompty",
    title="Supervisor prompt", description="Trim/condition the supervisor system prompt.",
    recipe=_prompt_recipe,
))

register(Seam(
    id="prompt:itinerary", kind="prompt", target="itinerary_agent.prompty",
    title="Itinerary agent prompt", description="Tune the itinerary generator prompt.",
    recipe=_prompt_recipe,
))

register(Seam(
    id="code:model-selector", kind="code", target="introduce-model-selector",
    title="Introduce a model selector",
    description="Add a per-turn model-selection code path (staged diff, human-reviewed).",
    recipe=_code_recipe,
))
