"""Static contract checks for the controlled Demo 4 API, portal, and simulators."""

from __future__ import annotations

import ast
from pathlib import Path

from validate_static_portal_freeze import validate_checked_in_portals


ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "02_completed" / "python" / "src" / "app" / "optimization_api.py"
COORDINATOR = (
    ROOT
    / "02_completed"
    / "python"
    / "src"
    / "app"
    / "services"
    / "lifecycle_coordinator.py"
)
DEMO_DATA = ROOT / "02_completed" / "python" / "src" / "app" / "services" / "demo_data.py"
PORTAL = ROOT / "02_completed" / "analytics-portal" / "index.html"
SIMULATOR = ROOT / "analytics" / "scripts" / "traffic_simulator.py"
WRAPPER = ROOT / "analytics" / "scripts" / "Run-TrafficSimulator.ps1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    validate_checked_in_portals()
    print("PASS: mirrored portal structure, classes, IDs, and CSS remain frozen")
    api = API.read_text(encoding="utf-8")
    coordinator = COORDINATOR.read_text(encoding="utf-8")
    demo_data = DEMO_DATA.read_text(encoding="utf-8")
    portal = PORTAL.read_text(encoding="utf-8")
    simulator = SIMULATOR.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")
    ast.parse(api)
    ast.parse(coordinator)
    ast.parse(demo_data)
    ast.parse(simulator)

    _require('@router.post("/{scenario}/apply")' in api, "existing Apply route retained")
    _require('@router.post("/traffic")' in api, "existing traffic route retained")
    _require(
        "_serialized_lifecycle" in api
        and "controlled_demo_lifecycle_busy" in api
        and api.count("@_serialized_lifecycle(") >= 5,
        "all lifecycle mutations share the bounded server coordinator",
    )
    _require(
        "CosmosLifecycleCoordinator" in api
        and "LifecycleLeaseUnavailable" in api
        and "MatchConditions.IfNotModified" in coordinator
        and "owner_token" in coordinator
        and "lease_expires_at_epoch" in coordinator
        and "configuration_store.get_container" in coordinator,
        "lifecycle coordinator is a fail-closed conditional Cosmos lease",
    )
    _require("transition" not in "\n".join(
        line for line in api.splitlines() if "@router." in line
    ).lower(), "no combined transition route")
    _require(
        "build_after_burst_manifest" in demo_data
        and "def build_after_burst_manifest" not in demo_data,
        "API service consumes the shared controlled manifest implementation",
    )
    _require(
        "tenant=analytics" in portal
        and "count=200" in portal
        and "minutes=20" in portal
        and "fixture_version=controlled-demo4-v1" in portal
        and "burst_version=controlled-demo4-after-v1" in portal
        and "anchor=2026-09-24T13%3A00%3A00Z" in portal,
        "portal uses checked-in Analytics/200/20/version/anchor defaults",
    )
    _require(
        "def run_controlled" in simulator
        and 'f"{base}/optimizations/traffic"' in simulator
        and '"controlled": "true"' in simulator
        and 'f"{tenant}::{MODEL_SELECTION_SCENARIO}"' in simulator,
        "controlled CLI calls the existing API-owned shared path",
    )
    _require(
        'session = (created.json() or {}).get("sessionId")' in simulator
        and "returned no sessionId; skipping completion" in simulator
        and "sessions/{session}/completion" in simulator,
        "app mode requires and reuses the returned sessionId",
    )
    _require(
        "[switch]$Controlled" in wrapper
        and "'--controlled'" in wrapper
        and "controlled-demo4-after-v1" in wrapper,
        "PowerShell wrapper exposes the explicit controlled path and defaults",
    )
    _require(
        "setLifecycleRunning(true)" in portal
        and "controlled_demo_lifecycle_busy" not in portal
        and "responseError(res, txt)" in portal,
        "portal disables lifecycle mutations and surfaces server status/body errors",
    )
    print("Controlled Demo 4 control validation passed.")


if __name__ == "__main__":
    main()
