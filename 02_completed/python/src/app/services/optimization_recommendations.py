"""
Optimization recommendations (the *recommend* stage of the analytics loop).

Turns signal the app already captures (Debug turn logs) into candidate
"optimization cards" a dashboard can show and a user can apply with one click.
Today this produces the SCEN-007 (capability-tiered model selection) card.

IMPORTANT — pricing is ESTIMATED. The per-token prices below are public
list-price estimates (verify on the Azure pricing calculator before quoting).
They are used only for a rough *projected* saving; the authoritative number is
the measured before/after in the verify step (optimization_mining.py), because
reasoning models (gpt-5-nano / gpt-5.1) emit billed reasoning tokens that a
naive projection cannot know in advance.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from src.app.services import azure_cosmos_db as cosmos
from src.app.services import optimization_policy

logger = logging.getLogger(__name__)

# Estimated USD per 1M tokens (input, output). Single source of truth is
# python/data/model_pricing.json (also written to .env as MODEL_PRICING_JSON by the
# azd post-provision hook, and passed to the reverse-ETL notebook). Resolution order:
#   1. MODEL_PRICING_JSON env var (what .env / azd provides at runtime)
#   2. python/data/model_pricing.json (committed default)
#   3. the built-in dict below (last-resort fallback so the app never breaks)
_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.1": {"input": 1.25, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
}


def _normalize_pricing(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for model, v in (data or {}).items():
        if isinstance(v, dict) and "input" in v and "output" in v:
            out[model] = {"input": float(v["input"]), "output": float(v["output"])}
        elif isinstance(v, (list, tuple)) and len(v) >= 2:
            out[model] = {"input": float(v[0]), "output": float(v[1])}
    return out


def load_pricing() -> dict[str, dict[str, float]]:
    """Model pricing from env (MODEL_PRICING_JSON) → committed file → built-in default."""
    raw = os.getenv("MODEL_PRICING_JSON")
    if raw:
        try:
            parsed = _normalize_pricing(json.loads(raw))
            if parsed:
                return parsed
        except (ValueError, TypeError):
            logger.warning("Invalid MODEL_PRICING_JSON; falling back to the pricing file/default")
    try:
        path = Path(__file__).resolve().parents[3] / "data" / "model_pricing.json"
        if path.exists():
            parsed = _normalize_pricing(json.loads(path.read_text(encoding="utf-8")))
            if parsed:
                return parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read model_pricing.json (%s); using built-in default pricing", exc)
    return dict(_DEFAULT_PRICING)


ESTIMATED_PRICING: dict[str, dict[str, float]] = load_pricing()

MODEL_SELECTION_SCENARIO = "model-selection"

# The policy this card proposes (safe default: disabled until applied).
PROPOSED_MODEL_SELECTION_PARAMS: dict[str, Any] = {
    "enabled": True,
    "default_deployment": "gpt-5.1",
    "tiers": {
        "trivial": "gpt-5-nano",
        "routine": "gpt-5-mini",
        "complex": "gpt-5.1",
    },
    "classifier": {"trivial_max_words": 6},
}


def _bag(doc: dict) -> dict:
    p = doc.get("propertyBag")
    return {i["key"]: i["value"] for i in p} if isinstance(p, list) else (p or {})


def _query_debug(tenant_id: str) -> list[dict]:
    if cosmos.debug_logs_container is None:
        cosmos.initialize_cosmos_client()
    if cosmos.debug_logs_container is None:
        return []
    return list(
        cosmos.debug_logs_container.query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        )
    )


def build_model_selection_recommendation(tenant_id: str) -> dict[str, Any]:
    """Build the SCEN-007 candidate card from Debug turn logs for a tenant."""
    dbg = _query_debug(tenant_id)
    total = len(dbg)

    trivial = 0
    trivial_in = trivial_out = 0
    models: dict[str, int] = {}
    for d in dbg:
        b = _bag(d)
        models[b.get("model_name", "Unknown")] = models.get(b.get("model_name", "Unknown"), 0) + 1
        out = int(b.get("output_tokens") or 0)
        if str(b.get("handoff_count")) == "0" and out < 60:
            trivial += 1
            trivial_in += int(b.get("input_tokens") or 0)
            trivial_out += out

    # Estimated saving IF trivial turns moved from the default (gpt-5.1) -> nano,
    # using the tokens actually observed on those turns. Optimistic: ignores nano
    # reasoning tokens, which is why the verify step (measured before/after) is
    # the real proof.
    baseline = ESTIMATED_PRICING["gpt-5.1"]
    nano = ESTIMATED_PRICING["gpt-5-nano"]
    cost_now = (trivial_in * baseline["input"] + trivial_out * baseline["output"]) / 1_000_000
    cost_proposed = (trivial_in * nano["input"] + trivial_out * nano["output"]) / 1_000_000
    est_saving = round(cost_now - cost_proposed, 4)

    active = optimization_policy.get_active_policy(MODEL_SELECTION_SCENARIO)
    status = "active" if active else (
        (optimization_policy.get_policy(MODEL_SELECTION_SCENARIO) or {}).get("status", "not_proposed")
    )

    return {
        "scenario": MODEL_SELECTION_SCENARIO,
        "scenario_id": "SCEN-007",
        "title": "Capability-tiered model selection",
        "dimension": "model selection · cost efficiency",
        "maturity": "L4/L5 (lower-risk autonomous policy)",
        "status": status,
        "evidence": {
            "total_turns": total,
            "trivial_turns": trivial,
            "trivial_pct": round(100 * trivial / max(total, 1), 1),
            "model_distribution": models,
        },
        "estimated_saving_usd": est_saving,
        "estimate_caveat": (
            "ESTIMATE only. gpt-5-nano is a reasoning model that emits billed "
            "reasoning tokens, so trivial turns may not actually be cheaper. The "
            "measured before/after (verify step) is authoritative."
        ),
        "price_assumptions_usd_per_1m": ESTIMATED_PRICING,
        "proposed_params": PROPOSED_MODEL_SELECTION_PARAMS,
        "actions": {
            "propose": f"POST /optimizations/{MODEL_SELECTION_SCENARIO}/propose",
            "apply": f"POST /optimizations/{MODEL_SELECTION_SCENARIO}/apply",
            "revert": f"POST /optimizations/{MODEL_SELECTION_SCENARIO}/revert",
        },
    }


def build_recommendations(tenant_id: str) -> list[dict[str, Any]]:
    """Return all candidate optimization cards for a tenant."""
    return [build_model_selection_recommendation(tenant_id)]
