#!/usr/bin/env python3
"""
Seed the Cosmos ``Configuration`` container (runtime single-source config).

Run by the ``azd`` post-provision hook (and safe to run by hand). It:

1. Discovers the Azure OpenAI model *deployments* that ``azd`` actually deployed
   (``az cognitiveservices account deployment list``). The deployed models are
   the source of truth for *which* models exist — swap a model in Bicep and its
   priced row appears here automatically on the next ``azd up``.
2. Looks up each model's price in the committed reference ``data/model_pricing.json``
   (USD per 1M tokens; see ``analytics/docs/model-pricing.md``). A deployed model
   with no reference entry is priced at a default and a warning is printed so a
   maintainer knows to add it.
3. **Upserts** one flat row per model into ``Configuration`` (``type="model_pricing"``).
   Upsert (never delete) means older models' rows remain, so the Power BI report
   can show before/after a model swap until the turn data ages out.
4. Upserts a ``model_selection_defaults`` doc (the default tier/classifier policy
   the recommendation card proposes), making ``Configuration`` a genuine
   multi-entity config store rather than a single-purpose table.

Offline fallback: if ``az`` deployment discovery is unavailable (e.g. an attendee
running the offline seed), the models in ``model_pricing.json`` are used so the
container is still populated deterministically.

Run: ``python data/seed_configuration.py``
"""

import importlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from azure.cosmos import CosmosClient, PartitionKey, ThroughputProperties
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

COSMOS_ENDPOINT = os.getenv("COSMOSDB_ENDPOINT")
DATABASE_NAME = os.getenv("COSMOSDB_DATABASE_NAME", "TravelAssistant")
CONTAINER_NAME = "Configuration"

DATA_DIR = Path(__file__).resolve().parent
PRICING_REFERENCE = DATA_DIR / "model_pricing.json"

# Allow importing the app's service modules (src.app...) when run from python/.
_PYTHON_DIR = str(DATA_DIR.parent)
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

# Last-resort price for a deployed model missing from the reference file.
DEFAULT_PRICE = {"input": 1.25, "output": 10.00}

# Default tier/classifier policy the recommendation card proposes. Derived from the
# app's own PROPOSED_MODEL_SELECTION_PARAMS so the seeded doc matches the code
# default exactly (reading it back is behavior-neutral); this is the fallback.
_FALLBACK_MODEL_SELECTION_DEFAULTS = {
    "enabled": True,
    "default_deployment": "gpt-5.1",
    "tiers": {"trivial": "gpt-5-nano", "routine": "gpt-5-mini", "complex": "gpt-5.1"},
    "classifier": {"trivial_max_words": 6},
}


def load_model_selection_defaults() -> dict:
    """The tree's own proposed model-selection policy (02: optimization_recommendations,
    01: optimization), so the seeded doc equals the code default and reads are no-ops."""
    for mod_name in ("src.app.services.optimization_recommendations", "src.app.services.optimization"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001
            continue
        params = getattr(mod, "PROPOSED_MODEL_SELECTION_PARAMS", None) or getattr(
            mod, "_CODE_MODEL_SELECTION_PARAMS", None
        )
        if isinstance(params, dict) and params.get("tiers"):
            return dict(params)
    return dict(_FALLBACK_MODEL_SELECTION_DEFAULTS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_price_reference() -> dict[str, dict[str, float]]:
    """model -> {input, output} from the committed reference file."""
    if not PRICING_REFERENCE.exists():
        print(f"⚠️  {PRICING_REFERENCE.name} not found; using default price for all models")
        return {}
    try:
        raw = json.loads(PRICING_REFERENCE.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"⚠️  Could not read {PRICING_REFERENCE.name} ({exc}); using default price")
        return {}
    out: dict[str, dict[str, float]] = {}
    for model, v in (raw or {}).items():
        if isinstance(v, dict) and "input" in v and "output" in v:
            out[model] = {"input": float(v["input"]), "output": float(v["output"])}
        elif isinstance(v, (list, tuple)) and len(v) >= 2:
            out[model] = {"input": float(v[0]), "output": float(v[1])}
    return out


def _account_name_from_endpoint() -> str | None:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    if not endpoint:
        return None
    host = endpoint.split("://", 1)[-1].split("/", 1)[0]
    return host.split(".", 1)[0] or None


def discover_deployed_models() -> list[str]:
    """Model names of the Azure OpenAI deployments azd created (via `az`).

    Returns [] if discovery isn't possible (no az / not logged in / offline),
    letting the caller fall back to the reference file.
    """
    account = _account_name_from_endpoint()
    rg = os.getenv("AZURE_RESOURCE_GROUP") or os.getenv("RG_NAME")
    if not account or not rg:
        return []
    az = "az.cmd" if os.name == "nt" else "az"
    try:
        result = subprocess.run(
            [az, "cognitiveservices", "account", "deployment", "list",
             "-n", account, "-g", rg, "-o", "json"],
            capture_output=True, text=True, timeout=120,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        print(f"ℹ️  Deployment discovery via az unavailable ({exc}); using pricing reference")
        return []
    if result.returncode != 0:
        print(f"ℹ️  az deployment list failed ({result.stderr.strip()[:200]}); using pricing reference")
        return []
    try:
        deployments = json.loads(result.stdout or "[]")
    except ValueError:
        return []

    models: list[str] = []
    for d in deployments:
        model = (((d.get("properties") or {}).get("model") or {}).get("name")) or d.get("name")
        if not model:
            continue
        if "embedding" in model.lower():  # pricing here is for chat/completion models
            continue
        models.append(model)
    return models


def _get_container(client: CosmosClient):
    db = client.get_database_client(DATABASE_NAME)
    return db.create_container_if_not_exists(
        id=CONTAINER_NAME,
        partition_key=PartitionKey(path="/type"),
        offer_throughput=ThroughputProperties(auto_scale_max_throughput=1000),
    )


def main() -> int:
    if not COSMOS_ENDPOINT:
        print("❌ COSMOSDB_ENDPOINT not set; cannot seed Configuration")
        return 1

    reference = load_price_reference()
    deployed = discover_deployed_models()
    if deployed:
        print(f"🔎 Discovered {len(deployed)} deployed model(s): {', '.join(sorted(set(deployed)))}")
        models = sorted(set(deployed))
    else:
        models = sorted(reference.keys())
        print(f"🔎 Using {len(models)} model(s) from {PRICING_REFERENCE.name}: {', '.join(models)}")

    if not models:
        print("⚠️  No models to price; skipping model_pricing rows")

    client = CosmosClient(COSMOS_ENDPOINT, credential=DefaultAzureCredential())
    container = _get_container(client)
    now_epoch = int(time.time())

    priced = 0
    for model in models:
        price = reference.get(model)
        source = "reference"
        if price is None:
            price = DEFAULT_PRICE
            source = "default"
            print(f"⚠️  No price for '{model}' in {PRICING_REFERENCE.name}; "
                  f"defaulting to ${DEFAULT_PRICE['input']}/${DEFAULT_PRICE['output']} per 1M "
                  f"— add it (see analytics/docs/model-pricing.md)")
        container.upsert_item({
            "id": f"model_pricing::{model}",
            "type": "model_pricing",
            "model": model,
            "input_price": float(price["input"]),
            "output_price": float(price["output"]),
            "source": source,
            "updated_epoch": now_epoch,
            "updated_at": _now_iso(),
        })
        priced += 1
        print(f"  ✓ {model}: input ${price['input']} / output ${price['output']} per 1M ({source})")

    container.upsert_item({
        "id": "model_selection_defaults",
        "type": "model_selection_defaults",
        **load_model_selection_defaults(),
        "updated_epoch": now_epoch,
        "updated_at": _now_iso(),
    })
    print("  ✓ model_selection_defaults")

    print(f"✅ Configuration seeded: {priced} model_pricing row(s) + defaults")
    return 0


if __name__ == "__main__":
    sys.exit(main())
