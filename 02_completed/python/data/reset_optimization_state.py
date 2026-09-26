"""Back up and restore the deterministic controlled Demo 4 baseline."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from src.app.services import demo_data
from src.app.services.controlled_demo4 import DEFAULT_ANCHOR, FIXTURE_VERSION, TURN_COUNT


def main() -> None:
    load_dotenv(override=False)
    ap = argparse.ArgumentParser(description="Restore the controlled Demo 4 fixture.")
    ap.add_argument("--fixture-version", default=FIXTURE_VERSION)
    ap.add_argument("--anchor", default=DEFAULT_ANCHOR)
    ap.add_argument("--count", type=int, default=TURN_COUNT)
    ap.add_argument(
        "--backup-dir",
        default=os.environ.get(
            "CONTROLLED_DEMO_BACKUP_DIR",
            str(
                Path(__file__).resolve().parents[2]
                / ".local"
                / "integration-evidence"
                / "controlled-demo4"
            ),
        ),
    )
    args = ap.parse_args()

    endpoint = os.environ.get("COSMOSDB_ENDPOINT")
    if not endpoint:
        raise SystemExit("COSMOSDB_ENDPOINT not set — run from the python/ dir with python/.env present.")
    db_name = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")

    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(db_name)
    result = demo_data.reset_controlled_demo4(
        db=db,
        fixture_version=args.fixture_version,
        anchor=args.anchor,
        count=args.count,
        backup_dir=args.backup_dir,
    )
    print(
        f"Restored {result['fixture_version']} for {', '.join(result['tenants'])}; "
        f"backup: {result['backup_path']}"
    )
    print("OptimizationInsights and OptimizationGovernance remain empty until Recompute.")


if __name__ == "__main__":
    main()
