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

AUTH
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
CONFIG_CONTAINER = "Configuration"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lookup_params(database, scenario: str) -> dict[str, Any]:
    """Read the scenario's canonical params from the app's Configuration container so
    the tiers/models live in ONE place (seeded from the models azd actually deployed) —
    never duplicated here. Falls back to a minimal enabled flag if not seeded."""
    if scenario == "model-selection":
        try:
            cfg = database.get_container_client(CONFIG_CONTAINER)
            doc = cfg.read_item(item="model_selection_defaults", partition_key="model_selection_defaults")
            if isinstance(doc.get("tiers"), dict):
                return {
                    "enabled": bool(doc.get("enabled", True)),
                    "default_deployment": doc.get("default_deployment", "gpt-5.1"),
                    "tiers": doc["tiers"],
                    "classifier": doc.get("classifier", {}),
                }
        except Exception:  # noqa: BLE001 -- not seeded / not found -> minimal fallback
            pass
    return {"enabled": True}


def _set_status(database, scenario: str, status: str, by: str) -> dict[str, Any]:
    """Read-modify-write the policy doc: flip status, bump version, append audit.

    Mirrors the app's optimization_policy._transition so the app reads a consistent
    document (id == scenario, partition key /scenario). If the policy was never
    proposed from the console, seed it from the app's canonical Configuration params."""
    container = database.get_container_client(POLICIES_CONTAINER)
    try:
        doc = container.read_item(item=scenario, partition_key=scenario)
    except exceptions.CosmosResourceNotFoundError:
        doc = {
            "id": scenario, "scenario": scenario,
            "params": _lookup_params(database, scenario),
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
def apply_optimization(cosmos: CosmosClient, scenario: str, by: str = "powerbi") -> str:
    """Activate an optimization policy (status=active). The agent reads it per turn.

    Returns a string so it can drive a Power BI translytical (data function) button."""
    result = _set_status(cosmos.get_database_client(DB_NAME), scenario, "active", by)
    logging.info("apply_optimization: %s", result)
    return f"Applied '{scenario}' - status now {result['status']} (v{result['version']})."


@udf.connection(argName="cosmos", audienceType="CosmosDB", cosmos_endpoint=COSMOS_URI)
@udf.function()
def revert_optimization(cosmos: CosmosClient, scenario: str, by: str = "powerbi") -> str:
    """Roll back an optimization policy (status=reverted) - a safe, reversible flip.

    Returns a string so it can drive a Power BI translytical (data function) button."""
    result = _set_status(cosmos.get_database_client(DB_NAME), scenario, "reverted", by)
    logging.info("revert_optimization: %s", result)
    return f"Reverted '{scenario}' - status now {result['status']} (v{result['version']})."


@udf.connection(argName="cosmos", audienceType="CosmosDB", cosmos_endpoint=COSMOS_URI)
@udf.function()
def get_optimization_status(cosmos: CosmosClient, scenario: str) -> str:
    """Read the current status of a policy. Returns a string so the whole function set
    stays compatible with Power BI data-function buttons."""
    container = cosmos.get_database_client(DB_NAME).get_container_client(POLICIES_CONTAINER)
    try:
        doc = container.read_item(item=scenario, partition_key=scenario)
    except exceptions.CosmosResourceNotFoundError:
        return f"{scenario}: not_proposed"
    return f"{scenario}: {doc.get('status')} (v{doc.get('version')})"
