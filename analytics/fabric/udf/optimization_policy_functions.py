"""
Fabric User Data Function — translytical Apply / Revert for optimization policies.

WHAT
    Two functions that flip an ``OptimizationPolicies`` document in the workshop's
    Azure Cosmos DB account. Power BI "Apply" / "Revert" buttons (a translytical
    task flow) — or any REST caller — invoke these to drive the optimization
    apply-loop that the running agent reads per turn. This closes the
    operational<->analytical loop *inside the report*: click Apply in Power BI ->
    Fabric UDF writes Cosmos -> the agent's next turn honors the policy.

HOW TO DEPLOY (Fabric portal — see README.md for the full runbook)
    1. Data Engineering experience -> + New item -> "User data functions".
    2. New function -> paste this whole file.
    3. Library Management -> + Add from PyPI -> azure-cosmos (latest).
    4. Set COSMOS_URI and DB_NAME below.
    5. Publish. Then Test with scenario="model-selection".

AUTH (the part that bit us before)
    ``@udf.connection(audienceType="CosmosDB", cosmos_endpoint=COSMOS_URI)`` makes
    Fabric hand the function an Entra-authenticated CosmosClient. The identity
    Fabric uses MUST hold the **Cosmos DB Built-in Data Contributor** data-plane
    role on the target account (control-plane "Contributor" is NOT enough). See
    README.md for the one az command that grants it. If the managed connection
    cannot reach an *external* Azure Cosmos account (vs a Fabric-native Cosmos
    item), use the self-authenticated fallback in README.md.
"""
import logging
from datetime import datetime, timezone
from typing import Any

import fabric.functions as fn
from azure.cosmos import CosmosClient, exceptions

udf = fn.UserDataFunctions()

# --- configure these two for your deployment -------------------------------
COSMOS_URI = "https://YOUR-COSMOS-ACCOUNT.documents.azure.com:443/"
DB_NAME = "TravelAssistant"
# ---------------------------------------------------------------------------
POLICIES_CONTAINER = "OptimizationPolicies"

# Fallback params so Apply works even if the scenario was never proposed from the
# console. Keep model-selection in sync with the app's proposed params
# (Configuration type="model_selection_defaults" / the app's code default).
_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "model-selection": {
        "enabled": True,
        "classifier": {"trivial_max_output_tokens": 60, "trivial_requires_zero_handoffs": True},
        "tiers": {"trivial": "gpt-5-nano", "routine": "gpt-5-mini", "complex": "gpt-5.1"},
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_status(container, scenario: str, status: str, by: str) -> dict[str, Any]:
    """Read-modify-write the policy doc: flip status, bump version, append audit.

    Mirrors the app's optimization_policy._transition so the app reads a
    consistent document (id == scenario, partition key /scenario)."""
    try:
        doc = container.read_item(item=scenario, partition_key=scenario)
    except exceptions.CosmosResourceNotFoundError:
        doc = {
            "id": scenario, "scenario": scenario,
            "params": _DEFAULT_PARAMS.get(scenario, {"enabled": True}),
            "version": 0, "audit": [], "created_at": _now_iso(),
        }
    doc["status"] = status
    doc["updated_at"] = _now_iso()
    doc["version"] = int(doc.get("version", 0)) + 1
    doc.setdefault("audit", []).append({"ts": _now_iso(), "action": status, "by": by})
    container.upsert_item(doc)
    return {"scenario": scenario, "status": doc["status"],
            "version": doc["version"], "updated_at": doc["updated_at"]}


@udf.connection(argName="cosmos", audienceType="CosmosDB", cosmos_endpoint=COSMOS_URI)
@udf.function()
def apply_optimization(cosmos: CosmosClient, scenario: str, by: str = "powerbi") -> dict[str, Any]:
    """Activate an optimization policy (status=active). The agent reads it per turn."""
    container = cosmos.get_database_client(DB_NAME).get_container_client(POLICIES_CONTAINER)
    result = _set_status(container, scenario, "active", by)
    logging.info("apply_optimization: %s", result)
    return result


@udf.connection(argName="cosmos", audienceType="CosmosDB", cosmos_endpoint=COSMOS_URI)
@udf.function()
def revert_optimization(cosmos: CosmosClient, scenario: str, by: str = "powerbi") -> dict[str, Any]:
    """Roll back an optimization policy (status=reverted) — a safe, reversible flip."""
    container = cosmos.get_database_client(DB_NAME).get_container_client(POLICIES_CONTAINER)
    result = _set_status(container, scenario, "reverted", by)
    logging.info("revert_optimization: %s", result)
    return result


@udf.connection(argName="cosmos", audienceType="CosmosDB", cosmos_endpoint=COSMOS_URI)
@udf.function()
def get_optimization_status(cosmos: CosmosClient, scenario: str) -> dict[str, Any]:
    """Read the current status of a policy (handy to verify the writeback in tests)."""
    container = cosmos.get_database_client(DB_NAME).get_container_client(POLICIES_CONTAINER)
    try:
        doc = container.read_item(item=scenario, partition_key=scenario)
    except exceptions.CosmosResourceNotFoundError:
        return {"scenario": scenario, "status": "not_proposed"}
    return {"scenario": scenario, "status": doc.get("status"),
            "version": doc.get("version"), "updated_at": doc.get("updated_at")}
