"""Fail-closed orchestration for controlled Demo 4 deployment verification.

The orchestration layer is deliberately dependency-injected.  Unit tests use local fakes,
while the CLI supplies Cosmos, identity, HTTP, azd, Container Apps, Fabric, and Power BI
adapters.  Mode plans are explicit so a baseline run cannot accidentally grow into the
Apply/traffic/recompute sequence.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from src.app.services.controlled_demo4 import (
    BURST_ANCHOR,
    BURST_VERSION,
    CANONICAL_MINUTE_PROFILE,
    COHORT_CONTAINERS,
    CONFIRMED_TRIP_COUNT,
    DEFAULT_ANCHOR,
    DERIVED_CONTAINERS,
    EXPECTED_FUNNEL,
    FIXTURE_VERSION,
    PREMIUM_DEPLOYMENT,
    PREMIUM_MODEL,
    SESSION_COUNT,
    TENANTS,
    TURN_COUNT,
    WINDOW_MINUTES,
    build_after_burst_manifest,
    build_tenant_manifest,
    controlled_fixture_session_prefix,
    is_controlled_fixture_row,
    is_controlled_trip,
    normalized_fingerprint,
)

MODES = (
    "baseline-live",
    "post-traffic",
    "backup-only",
    "restore",
    "manifest-only",
    "local-simulation",
)
RECOMPUTE_CHOICES = ("none", "in-process", "fabric")
DEPLOYMENT_TRANSPORTS = ("auto", "direct", "azd")
MODEL_SELECTION_SCENARIO = "model-selection"
AFFECTED_CONTAINERS = (*COHORT_CONTAINERS, *DERIVED_CONTAINERS)
PROTECTED_CONTAINERS = ("Users", "Memories", "memories", "Checkpoints", "ApiEvents")
MIRROR_TABLES = (
    "OptimizationTurns",
    "NodeExecutions",
    "Trips",
    "OptimizationPolicies",
    "OptimizationGovernance",
    "Configuration",
    "Messages",
    "ApiEvents",
    "OptimizationInsights",
    "memories",
)
BASELINE_COUNTS = {
    "OptimizationTurns": TURN_COUNT,
    "Debug": TURN_COUNT,
    "NodeExecutions": TURN_COUNT,
    "Sessions": SESSION_COUNT,
    "Messages": TURN_COUNT,
    "Trips": CONFIRMED_TRIP_COUNT,
    "OptimizationInsights": 0,
    "OptimizationGovernance": 0,
}
FORBIDDEN_BASELINE_OPERATIONS = {
    "apply",
    "traffic",
    "recompute_in_process",
    "fabric_controller",
    "freshen_times",
}


class VerificationError(RuntimeError):
    """A blocking verifier invariant failed."""


class Runtime(Protocol):
    def identity_preflight(self) -> dict[str, Any]: ...
    def capture_backup(self, path: Path, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def capture_deployment_inventory(self, backup_path: Path) -> dict[str, Any]: ...
    def deploy_existing_topology(self) -> dict[str, Any]: ...
    def deployment_mutated(self) -> bool: ...
    def rollback_deployment(self, inventory: dict[str, Any]) -> dict[str, Any]: ...
    def reset(self) -> dict[str, Any]: ...
    def direct_snapshot(self) -> dict[str, Any]: ...
    def poll_mirror(self, expectation: dict[str, Any], timeout_seconds: int) -> dict[str, Any]: ...
    def verify_power_bi_baseline(self, tenants: tuple[str, ...]) -> dict[str, Any]: ...
    def recompute_in_process(self) -> dict[str, Any]: ...
    def run_fabric_controller(self) -> dict[str, Any]: ...
    def verify_hosted_api(self) -> dict[str, Any]: ...
    def restore(self, path: Path) -> dict[str, Any]: ...
    def git_head(self) -> str: ...


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_cosmos_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in document.items()
        if key not in {"_rid", "_self", "_etag", "_attachments", "_ts"}
    }


def _resolve_partition_key(document: dict[str, Any], paths: Iterable[str]) -> list[Any]:
    values: list[Any] = []
    for path in paths:
        current: Any = document
        for segment in path.strip("/").split("/"):
            if not isinstance(current, dict) or segment not in current:
                raise VerificationError(
                    f"document {document.get('id', '<unknown>')} lacks partition-key path {path}"
                )
            current = current[segment]
        values.append(current)
    return values


def _scope_summary(documents: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(documents, key=lambda row: (str(row.get("id")), sha256_json(row)))
    return {"count": len(ordered), "sha256": sha256_json(ordered)}


def write_durable_json(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Write, fsync, close, reread, and hash-check a backup before returning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    with path.open("rb") as handle:
        reread = handle.read()
    expected = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    actual = hashlib.sha256(reread).hexdigest()
    if actual != expected:
        raise VerificationError(
            f"backup reread integrity failure for {path}: expected {expected}, got {actual}"
        )
    decoded = json.loads(reread.decode("utf-8"))
    if decoded != payload:
        raise VerificationError(f"backup reread content mismatch for {path}")
    return {"path": str(path), "sha256": actual, "bytes": len(reread)}


def validate_backup_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise VerificationError(f"cannot read backup manifest {path}: {exc}") from exc
    integrity = payload.get("integrity", {})
    expected = integrity.get("manifest_sha256")
    candidate = copy.deepcopy(payload)
    candidate.pop("integrity", None)
    actual = sha256_json(candidate)
    if not expected or actual != expected:
        raise VerificationError(
            f"backup manifest integrity failure: expected {expected or '<missing>'}, got {actual}"
        )
    return payload


def _decode_claims(token: str) -> dict[str, Any]:
    try:
        body = token.split(".")[1]
        body += "=" * (-len(body) % 4)
        return json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    except Exception as exc:
        raise VerificationError("token acquisition returned a token with unreadable claims") from exc


class TokenProvider(Protocol):
    def get_token(self, resource: str) -> str: ...


class ChainedTokenProvider:
    """Try injected providers in order without logging token values."""

    def __init__(self, providers: Iterable[TokenProvider]):
        self.providers = tuple(providers)

    def get_token(self, resource: str) -> str:
        failures: list[str] = []
        for provider in self.providers:
            try:
                token = provider.get_token(resource)
                if token:
                    return token
            except Exception as exc:
                failures.append(f"{type(provider).__name__}: {exc}")
        raise VerificationError(
            f"token acquisition failed for {resource}; providers: {'; '.join(failures)}"
        )


class AzurePowerShellTokenProvider:
    """Windows-safe Get-AzAccessToken pattern supporting SecureString token output."""

    def get_token(self, resource: str) -> str:
        escaped = resource.replace("'", "''")
        script = (
            f"$r=Get-AzAccessToken -ResourceUrl '{escaped}';"
            "if($r.Token -is [securestring]){"
            "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($r.Token);"
            "try{[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p)}"
            "finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}}"
            "else{$r.Token}"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise VerificationError(result.stderr.strip() or "Get-AzAccessToken failed")
        return result.stdout.strip()


class AzurePowerShellTokenCredential:
    """azure-core TokenCredential adapter backed by the active Azure PowerShell context."""

    def __init__(self, provider: TokenProvider | None = None):
        self.provider = provider or AzurePowerShellTokenProvider()

    def get_token(self, *scopes: str, **_: Any) -> Any:
        if not scopes:
            raise VerificationError("at least one token scope is required")
        scope = scopes[0]
        resource = scope[: -len(".default")] if scope.endswith("/.default") else scope
        token = self.provider.get_token(resource)
        claims = _decode_claims(token)
        expires_on = int(claims.get("exp") or (time.time() + 300))
        from azure.core.credentials import AccessToken

        return AccessToken(token, expires_on)


class DefaultCredentialTokenProvider:
    def __init__(self, credential: Any = None):
        if credential is None:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
        self.credential = credential

    def get_token(self, resource: str) -> str:
        scope = resource.rstrip("/") + "/.default"
        return self.credential.get_token(scope).token


class AzureCliTokenProvider:
    def get_token(self, resource: str) -> str:
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", resource, "--query", "accessToken", "-o", "tsv"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise VerificationError(result.stderr.strip() or "Azure CLI token acquisition failed")
        return result.stdout.strip()


@dataclass(frozen=True)
class IdentityIntent:
    tenant_id: str
    subscription_id: str
    cosmos_account: str
    cosmos_endpoint: str


class IdentityPreflight:
    ARM_RESOURCE = "https://management.azure.com/"
    COSMOS_RESOURCE = "https://cosmos.azure.com/"
    FABRIC_RESOURCE = "https://api.fabric.microsoft.com/"
    POWER_BI_RESOURCE = "https://analysis.windows.net/powerbi/api"

    def __init__(
        self,
        intent: IdentityIntent,
        token_provider: TokenProvider,
        arm_lookup: Callable[[], dict[str, Any]],
    ):
        self.intent = intent
        self.token_provider = token_provider
        self.arm_lookup = arm_lookup

    def run(self) -> dict[str, Any]:
        actual = self.arm_lookup()
        expected_account = self.intent.cosmos_account.lower()
        actual_endpoint = str(actual.get("cosmos_endpoint", "")).rstrip("/").lower()
        checks = {
            "tenant": str(actual.get("tenant_id", "")).lower() == self.intent.tenant_id.lower(),
            "subscription": str(actual.get("subscription_id", "")).lower()
            == self.intent.subscription_id.lower(),
            "account": str(actual.get("cosmos_account", "")).lower() == expected_account,
            "endpoint": actual_endpoint == self.intent.cosmos_endpoint.rstrip("/").lower(),
        }
        if not all(checks.values()):
            failed = ", ".join(key for key, ok in checks.items() if not ok)
            raise VerificationError(f"identity preflight mismatch: {failed}")
        claims: dict[str, dict[str, Any]] = {}
        for name, resource in (
            ("arm", self.ARM_RESOURCE),
            ("cosmos", self.COSMOS_RESOURCE),
            ("fabric", self.FABRIC_RESOURCE),
            ("power_bi", self.POWER_BI_RESOURCE),
        ):
            decoded = _decode_claims(self.token_provider.get_token(resource))
            tenant = str(decoded.get("tid", "")).lower()
            if tenant != self.intent.tenant_id.lower():
                raise VerificationError(
                    f"{name} token tenant differs from intended azd tenant"
                )
            claims[name] = {
                "tenant_id": tenant,
                "audience": decoded.get("aud"),
                "object_id": decoded.get("oid"),
            }
        return {
            "status": "PASS",
            "tenant_id": self.intent.tenant_id,
            "subscription_id": self.intent.subscription_id,
            "cosmos_account": self.intent.cosmos_account,
            "cosmos_endpoint": self.intent.cosmos_endpoint,
            "token_claims": claims,
        }


class CosmosBackupStore:
    """Capture and targeted-restore the controlled scope through Cosmos container APIs."""

    def __init__(
        self,
        database: Any,
        *,
        endpoint: str,
        database_name: str,
        policy_service: Any,
    ):
        self.database = database
        self.endpoint = endpoint.rstrip("/")
        self.database_name = database_name
        self.policy_service = policy_service

    def _container(self, name: str) -> Any:
        return self.database.get_container_client(name)

    def _metadata(self, name: str) -> tuple[Any, list[str]]:
        container = self._container(name)
        definition = container.read()
        paths = definition.get("partitionKey", {}).get("paths", [])
        if not paths:
            raise VerificationError(f"container {name} has no resolvable partition-key paths")
        return container, paths

    @staticmethod
    def _query(container: Any, query: str, parameters: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        return [
            _clean_cosmos_document(row)
            for row in container.query_items(
                query=query,
                parameters=parameters or [],
                enable_cross_partition_query=True,
            )
        ]

    def capture(self, path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
        documents: dict[str, list[dict[str, Any]]] = {}
        partition_paths: dict[str, list[str]] = {}
        scopes: dict[str, dict[str, Any]] = {}

        for name in AFFECTED_CONTAINERS:
            container, paths = self._metadata(name)
            partition_paths[name] = paths
            rows = self._query(
                container,
                "SELECT * FROM c WHERE ARRAY_CONTAINS(@tenants, c.tenantId)",
                [{"name": "@tenants", "value": list(TENANTS)}],
            )
            documents[name] = [
                {
                    "id": row["id"],
                    "partition_key": _resolve_partition_key(row, paths),
                    "document": row,
                }
                for row in rows
            ]
            for tenant in TENANTS:
                scopes[f"{name}:{tenant}"] = _scope_summary(
                    [row for row in rows if row.get("tenantId") == tenant]
                )

        policy_container, policy_paths = self._metadata("OptimizationPolicies")
        policies = self._query(policy_container, "SELECT * FROM c")
        partition_paths["OptimizationPolicies"] = policy_paths
        documents["OptimizationPolicies"] = [
            {
                "id": row["id"],
                "partition_key": _resolve_partition_key(row, policy_paths),
                "document": row,
            }
            for row in policies
        ]
        scopes["OptimizationPolicies:all"] = _scope_summary(policies)

        protected: dict[str, dict[str, Any]] = {}
        for name in PROTECTED_CONTAINERS:
            try:
                container, _ = self._metadata(name)
            except Exception:
                protected[name] = {"present": False, "count": 0, "sha256": sha256_json([])}
                continue
            rows = self._query(container, "SELECT * FROM c")
            protected[name] = {"present": True, **_scope_summary(rows)}

        for name in AFFECTED_CONTAINERS:
            container, _ = self._metadata(name)
            unrelated = self._query(
                container,
                "SELECT * FROM c WHERE NOT ARRAY_CONTAINS(@tenants, c.tenantId)",
                [{"name": "@tenants", "value": list(TENANTS)}],
            )
            protected[f"{name}:unrelated"] = _scope_summary(unrelated)
            globals_ = [
                row
                for row in unrelated
                if str(row.get("tenantId", "")).startswith("_global")
            ]
            protected[f"{name}:global-memory"] = _scope_summary(globals_)
        for tenant in TENANTS:
            protected[f"Trips:{tenant}:operational"] = _scope_summary(
                [
                    entry["document"]
                    for entry in documents["Trips"]
                    if entry["document"].get("tenantId") == tenant
                    and not is_controlled_trip(entry["document"], tenant)
                ]
            )

        baseline_ids = {
            name: sorted(
                {
                    row["id"]
                    for tenant in TENANTS
                    for row in build_tenant_manifest(
                        tenant,
                        fixture_version=arguments.get("fixture", FIXTURE_VERSION),
                        anchor=arguments.get("anchor", DEFAULT_ANCHOR),
                        count=int(arguments.get("count", TURN_COUNT)),
                    )[name]
                }
            )
            for name in COHORT_CONTAINERS
        }
        burst = build_after_burst_manifest(
            fixture_version=arguments.get("fixture", FIXTURE_VERSION),
            burst_version=arguments.get("burst", BURST_VERSION),
            anchor=arguments.get("burst_anchor", BURST_ANCHOR),
            count=int(arguments.get("count", TURN_COUNT)),
            window_minutes=int(arguments.get("window_minutes", WINDOW_MINUTES)),
        )
        for name in COHORT_CONTAINERS:
            baseline_ids[name] = sorted(
                set(baseline_ids[name]) | {row["id"] for row in burst[name]}
            )
        for name in DERIVED_CONTAINERS:
            baseline_ids[name] = sorted(
                entry["id"]
                for entry in documents[name]
                if any(
                    is_controlled_fixture_row(name, entry["document"], tenant)
                    for tenant in TENANTS
                )
            )

        manifest: dict[str, Any] = {
            "schema_version": 2,
            "capture_utc": _utc_now(),
            "cosmos": {
                "account_endpoint": self.endpoint,
                "account_name": urllib.parse.urlparse(self.endpoint).hostname.split(".")[0],
                "database": self.database_name,
            },
            "arguments": copy.deepcopy(arguments),
            "tenants": list(TENANTS),
            "affected_containers": list(AFFECTED_CONTAINERS),
            "protected_containers": list(PROTECTED_CONTAINERS),
            "partition_key_paths": partition_paths,
            "documents": documents,
            "scopes": scopes,
            "protected": protected,
            "owned_ids": baseline_ids,
            "controlled_namespaces": {
                name: {
                    "tenants": list(TENANTS),
                    "saved_ids": sorted(entry["id"] for entry in documents[name]),
                    "verifier_owned_ids": baseline_ids[name],
                }
                for name in AFFECTED_CONTAINERS
            },
        }
        manifest["integrity"] = {"manifest_sha256": sha256_json(manifest)}
        receipt = write_durable_json(path, manifest)
        return {"status": "PASS", "manifest": receipt, "scopes": scopes, "protected": protected}

    def restore(self, path: Path) -> dict[str, Any]:
        manifest = validate_backup_manifest(path)
        captured_cosmos = manifest.get("cosmos", {})
        if (
            str(captured_cosmos.get("account_endpoint", "")).rstrip("/").lower()
            != self.endpoint.lower()
            or captured_cosmos.get("database") != self.database_name
        ):
            raise VerificationError(
                "backup manifest Cosmos account/database differs from the restore target"
            )
        failures: list[str] = []
        restore_plans: dict[str, dict[str, Any]] = {}
        for name in AFFECTED_CONTAINERS:
            container, paths = self._metadata(name)
            saved = manifest["documents"].get(name, [])
            for entry in saved:
                if _resolve_partition_key(entry["document"], paths) != entry["partition_key"]:
                    failures.append(
                        f"{name}/{entry['id']} saved partition key differs from document"
                    )
            saved_by_key = {
                (entry["id"], tuple(entry["partition_key"])): entry for entry in saved
            }
            namespace = manifest.get("controlled_namespaces", {}).get(name, {})
            owned_ids = set(
                namespace.get(
                    "verifier_owned_ids", manifest.get("owned_ids", {}).get(name, [])
                )
            )
            current = self._query(
                container,
                "SELECT * FROM c WHERE ARRAY_CONTAINS(@tenants, c.tenantId)",
                [{"name": "@tenants", "value": list(TENANTS)}],
            )
            current_keys = {
                (row["id"], tuple(_resolve_partition_key(row, paths))): row
                for row in current
            }
            conflicts = sorted(
                f"{row_id}@{list(partition_key)}"
                for (row_id, partition_key) in current_keys
                if (row_id, partition_key) not in saved_by_key and row_id not in owned_ids
            )
            if conflicts:
                failures.append(
                    f"{name} restore conflict outside verifier-owned namespace: {conflicts}"
                )
            restore_plans[name] = {
                "container": container,
                "paths": paths,
                "saved": saved,
                "saved_by_key": saved_by_key,
                "owned_ids": owned_ids,
                "current": current,
            }

        policy_entries = manifest["documents"].get("OptimizationPolicies", [])
        saved_policies = {entry["id"]: entry["document"] for entry in policy_entries}
        policy_container, _ = self._metadata("OptimizationPolicies")
        current_policies = self._query(policy_container, "SELECT * FROM c")
        policy_conflicts = sorted(
            row["id"]
            for row in current_policies
            if row["id"] not in {
                f"{tenant}::{MODEL_SELECTION_SCENARIO}" for tenant in TENANTS
            }
            and (
                row["id"] not in saved_policies
                or sha256_json(row) != sha256_json(saved_policies[row["id"]])
            )
        )
        if policy_conflicts:
            failures.append(
                "OptimizationPolicies restore conflict outside model-selection lifecycle: "
                f"{policy_conflicts}"
            )
        if failures:
            raise VerificationError("restore conflict: " + "; ".join(failures))

        for name, plan in restore_plans.items():
            container = plan["container"]
            paths = plan["paths"]
            saved = plan["saved"]
            saved_by_key = plan["saved_by_key"]
            owned_ids = plan["owned_ids"]
            current = plan["current"]
            for row in current:
                row_key = (row["id"], tuple(_resolve_partition_key(row, paths)))
                if row["id"] in owned_ids and row_key not in saved_by_key:
                    try:
                        container.delete_item(
                            item=row["id"],
                            partition_key=_resolve_partition_key(row, paths),
                        )
                    except Exception as exc:
                        failures.append(f"{name}/{row['id']} delete: {exc}")
            for entry in saved:
                try:
                    container.upsert_item(copy.deepcopy(entry["document"]))
                except Exception as exc:
                    failures.append(f"{name}/{entry['id']} restore: {exc}")
            restored = self._query(
                container,
                "SELECT * FROM c WHERE ARRAY_CONTAINS(@tenants, c.tenantId)",
                [{"name": "@tenants", "value": list(TENANTS)}],
            )
            expected = [entry["document"] for entry in saved]
            restored_controlled = [
                row
                for row in restored
                if (row["id"], tuple(_resolve_partition_key(row, paths))) in saved_by_key
            ]
            if _scope_summary(restored_controlled) != _scope_summary(expected):
                failures.append(f"{name} restored count/hash mismatch")

        controlled_policies = {
            entry["id"]: entry["document"]
            for entry in policy_entries
            if entry["id"] in {
                f"{tenant}::{MODEL_SELECTION_SCENARIO}" for tenant in TENANTS
            }
        }
        for tenant in TENANTS:
            policy_id = f"{tenant}::{MODEL_SELECTION_SCENARIO}"
            policy = controlled_policies.get(policy_id)
            if policy is None:
                failures.append(f"{policy_id} policy missing from backup")
                continue
            try:
                restored = self.policy_service.restore_policy_snapshot(policy)
                if sha256_json(_clean_cosmos_document(restored)) != sha256_json(policy):
                    failures.append(f"{policy_id} policy restored hash mismatch")
            except Exception as exc:
                failures.append(f"{policy_id} lifecycle restore: {exc}")
        current_policies = self._query(policy_container, "SELECT * FROM c")
        expected_policies = [entry["document"] for entry in policy_entries]
        if _scope_summary(current_policies) != _scope_summary(expected_policies):
            failures.append("OptimizationPolicies restored count/hash mismatch")

        current_protected = self.protected_hashes()
        for scope, expected in manifest["protected"].items():
            if current_protected.get(scope) != expected:
                failures.append(f"protected scope changed: {scope}")
        if failures:
            raise VerificationError("partial restore: " + "; ".join(failures))
        return {"status": "PASS", "restored_manifest": str(path)}

    def protected_hashes(self) -> dict[str, dict[str, Any]]:
        protected: dict[str, dict[str, Any]] = {}
        for name in PROTECTED_CONTAINERS:
            try:
                container, _ = self._metadata(name)
                rows = self._query(container, "SELECT * FROM c")
                protected[name] = {"present": True, **_scope_summary(rows)}
            except Exception:
                protected[name] = {"present": False, "count": 0, "sha256": sha256_json([])}
        for name in AFFECTED_CONTAINERS:
            container, _ = self._metadata(name)
            unrelated = self._query(
                container,
                "SELECT * FROM c WHERE NOT ARRAY_CONTAINS(@tenants, c.tenantId)",
                [{"name": "@tenants", "value": list(TENANTS)}],
            )
            protected[f"{name}:unrelated"] = _scope_summary(unrelated)
            protected[f"{name}:global-memory"] = _scope_summary(
                [
                    row
                    for row in unrelated
                    if str(row.get("tenantId", "")).startswith("_global")
                ]
            )
        trips = self._query(
            self._container("Trips"),
            "SELECT * FROM c WHERE ARRAY_CONTAINS(@tenants, c.tenantId)",
            [{"name": "@tenants", "value": list(TENANTS)}],
        )
        for tenant in TENANTS:
            protected[f"Trips:{tenant}:operational"] = _scope_summary(
                [
                    row
                    for row in trips
                    if row.get("tenantId") == tenant
                    and not is_controlled_trip(row, tenant)
                ]
            )
        return protected


def validate_baseline_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate the exact raw baseline independently for each controlled tenant."""
    tenants = snapshot.get("tenants", {})
    results: dict[str, Any] = {}
    fingerprints: dict[str, str] = {}
    for tenant in TENANTS:
        containers = tenants.get(tenant, {})
        counts = {name: len(containers.get(name, [])) for name in BASELINE_COUNTS}
        if counts != BASELINE_COUNTS:
            raise VerificationError(
                f"{tenant} baseline counts differ: expected {BASELINE_COUNTS}, got {counts}"
            )
        turns = containers["OptimizationTurns"]
        debug = {row["turnId"]: row for row in containers["Debug"]}
        buckets: dict[datetime, int] = {}
        for row in turns:
            try:
                timestamp = datetime.fromisoformat(str(row["timeStamp"]).replace("Z", "+00:00"))
            except (TypeError, ValueError) as exc:
                raise VerificationError(
                    f"{tenant} contains an invalid baseline timestamp for {row.get('id')}"
                ) from exc
            if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
                raise VerificationError(
                    f"{tenant} baseline timestamp must use UTC for {row.get('id')}"
                )
            minute = timestamp.astimezone(timezone.utc).replace(second=0, microsecond=0)
            buckets[minute] = buckets.get(minute, 0) + 1
            if (
                row.get("model_deployment") != PREMIUM_DEPLOYMENT
                or row.get("model_name") != PREMIUM_MODEL
                or row.get("complexity_tier") != "default"
            ):
                raise VerificationError(f"{tenant} contains non-premium baseline turn {row.get('id')}")
            if BURST_VERSION in str(row.get("id")):
                raise VerificationError(f"{tenant} contains an after-burst ID at baseline")
            paired = debug.get(row["id"])
            if not paired or paired.get("timeStamp") != row.get("timeStamp") or paired.get("turn_epoch") != row.get("turn_epoch"):
                raise VerificationError(f"{tenant} timestamp/turn_epoch mismatch for {row.get('id')}")
        ordered_bucket_profile = tuple(buckets[minute] for minute in sorted(buckets))
        if (
            len(buckets) != len(CANONICAL_MINUTE_PROFILE)
            or ordered_bucket_profile != CANONICAL_MINUTE_PROFILE
        ):
            raise VerificationError(
                f"{tenant} minute buckets must match the exact canonical non-flat profile "
                f"{CANONICAL_MINUTE_PROFILE}; got {ordered_bucket_profile} across "
                f"{len(buckets)} ordered UTC minute buckets"
            )
        expected_manifest = {
            name: containers[name]
            for name in COHORT_CONTAINERS
        }
        fingerprints[tenant] = normalized_fingerprint(
            {
                name: sorted(rows, key=lambda row: str(row.get("id")))
                for name, rows in expected_manifest.items()
            }
        )
        funnel = snapshot.get("funnel", {}).get(tenant, {})
        if funnel.get("stages") != EXPECTED_FUNNEL:
            raise VerificationError(f"{tenant} funnel differs from {EXPECTED_FUNNEL}")
        if float(funnel.get("conversion_rate", -1)) != 29.2:
            raise VerificationError(f"{tenant} conversion must be 29.2%")
        if funnel.get("largest_cause") != {"name": "city_friction", "count": 52}:
            raise VerificationError(f"{tenant} city_friction=52 must be the largest cause")
        results[tenant] = {"counts": counts, "buckets": len(buckets)}
    if len(set(fingerprints.values())) != 1:
        raise VerificationError("identity-normalized tenant fingerprints differ")
    policy_statuses = snapshot.get("policy_statuses", {})
    if policy_statuses != {tenant: "reverted" for tenant in TENANTS}:
        raise VerificationError(
            "tenant-qualified model-selection policies are not both reverted"
        )
    if snapshot.get("protected_unchanged") is not True:
        raise VerificationError("protected hashes changed")
    return {"status": "PASS", "tenants": results, "fingerprints": fingerprints}


def summarize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "tenants": {
            tenant: {
                "counts": {
                    name: len(rows)
                    for name, rows in snapshot.get("tenants", {}).get(tenant, {}).items()
                },
                "hashes": {
                    name: sha256_json(
                        sorted(rows, key=lambda row: str(row.get("id")))
                    )
                    for name, rows in snapshot.get("tenants", {}).get(tenant, {}).items()
                },
                "funnel": snapshot.get("funnel", {}).get(tenant),
                "evaluation": snapshot.get("evaluations", {}).get(tenant),
            }
            for tenant in TENANTS
        },
        "policy_statuses": snapshot.get("policy_statuses"),
        "protected_unchanged": snapshot.get("protected_unchanged"),
    }


def poll_mirror_convergence(
    probe: Callable[[], dict[str, Any]],
    expectation: dict[str, Any],
    *,
    timeout_seconds: int,
    interval_seconds: float = 2.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    deadline = clock() + timeout_seconds
    last: dict[str, Any] = {}
    required_tables = set(MIRROR_TABLES)
    while clock() <= deadline:
        last = probe()
        mounted = set(last.get("mounted_tables", []))
        missing_tables = sorted(required_tables - mounted)
        exact_ids = bool(last.get("exact_controlled_ids"))
        stale_deleted = bool(last.get("stale_derived_rows_deleted"))
        if not missing_tables and exact_ids and stale_deleted:
            return {
                **copy.deepcopy(last),
                "status": "PASS",
                "mounted_tables": sorted(mounted),
                "attempts": last.get("attempts"),
            }
        sleep(interval_seconds)
    raise VerificationError(
        "mirror convergence timed out; "
        f"missing mounted tables={sorted(required_tables - set(last.get('mounted_tables', [])))}, "
        f"exact_controlled_ids={last.get('exact_controlled_ids')}, "
        f"stale_derived_rows_deleted={last.get('stale_derived_rows_deleted')}, "
        f"last_observation={last.get('diagnostic', 'none')}"
    )


def verify_hosted_session(
    base_url: str,
    *,
    request: Callable[..., Any] = urllib.request.urlopen,
    tenant: str = "analytics",
    user: str = "controlled-demo4-verifier",
) -> dict[str, Any]:
    root = base_url.rstrip("/")
    create_url = (
        f"{root}/tenant/{urllib.parse.quote(tenant)}/user/{urllib.parse.quote(user)}/sessions"
        "?activeAgent=orchestrator&title=Controlled%20Demo%204%20verification"
    )
    create_request = urllib.request.Request(create_url, method="POST", data=b"")
    with request(create_request, timeout=60) as response:
        created = json.loads(response.read().decode("utf-8"))
    session_id = created.get("sessionId")
    if not session_id:
        raise VerificationError("hosted session creation did not return sessionId")
    completion_url = (
        f"{root}/tenant/{urllib.parse.quote(tenant)}/user/{urllib.parse.quote(user)}"
        f"/sessions/{urllib.parse.quote(session_id)}/completion"
    )
    body = json.dumps("Confirm hosted verification connectivity.").encode("utf-8")
    completion_request = urllib.request.Request(
        completion_url,
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with request(completion_request, timeout=180) as response:
        response.read()
    return {
        "status": "PASS",
        "session_id_reused": True,
        "completion_path": completion_url.replace(session_id, "<returned-session-id>"),
    }


@dataclass
class VerifierConfig:
    mode: str
    recompute: str = "none"
    backup_path: Path | None = None
    timeout_seconds: int = 900
    starting_git_sha: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.mode not in MODES:
            raise VerificationError(f"unsupported mode {self.mode}; choose one of {MODES}")
        if self.recompute not in RECOMPUTE_CHOICES:
            raise VerificationError(
                f"ambiguous recompute choice {self.recompute}; choose exactly one of {RECOMPUTE_CHOICES}"
            )
        if self.mode != "post-traffic" and self.recompute != "none":
            raise VerificationError("recompute choice is valid only in post-traffic mode")
        if self.mode in {"baseline-live", "backup-only", "restore"} and self.backup_path is None:
            raise VerificationError(f"{self.mode} requires --backup-dir/backup manifest path")


class ControlledDemo4Verifier:
    def __init__(self, runtime: Runtime, config: VerifierConfig):
        self.runtime = runtime
        self.config = config
        self.events: list[str] = []

    def _call(self, name: str, function: Callable[..., Any], *args: Any) -> Any:
        self.events.append(name)
        return function(*args)

    def _check_head(self) -> None:
        if self.config.starting_git_sha and self.runtime.git_head() != self.config.starting_git_sha:
            raise VerificationError("Git SHA changed during Brief F verification")

    def run(self) -> dict[str, Any]:
        self.config.validate()
        mode = self.config.mode
        if mode == "manifest-only":
            return self._manifest_only()
        if mode == "restore":
            identity = self._call("identity_preflight", self.runtime.identity_preflight)
            result = self._call("restore", self.runtime.restore, self.config.backup_path)
            self._check_head()
            return self._result({"identity": identity, **result})

        identity = self._call("identity_preflight", self.runtime.identity_preflight)
        if mode == "backup-only":
            backup = self._call(
                "backup",
                self.runtime.capture_backup,
                self.config.backup_path,
                self.config.arguments,
            )
            self._check_head()
            return self._result({"identity": identity, "backup": backup})
        if mode == "baseline-live":
            return self._baseline_live(identity)
        if mode == "post-traffic":
            return self._post_traffic(identity)
        return self._local_simulation(identity)

    def _manifest_only(self) -> dict[str, Any]:
        self._check_head()
        return self._result(
            {
                "modes": list(MODES),
                "recompute_choices": list(RECOMPUTE_CHOICES),
                "deployment_transports": list(DEPLOYMENT_TRANSPORTS),
                "baseline_forbidden_operations": sorted(FORBIDDEN_BASELINE_OPERATIONS),
                "affected_containers": list(AFFECTED_CONTAINERS),
                "protected_containers": list(PROTECTED_CONTAINERS),
                "mirror_tables": list(MIRROR_TABLES),
            }
        )

    def _baseline_live(self, identity: dict[str, Any]) -> dict[str, Any]:
        backup = self._call(
            "backup",
            self.runtime.capture_backup,
            self.config.backup_path,
            self.config.arguments,
        )
        inventory = self._call(
            "deployment_inventory",
            self.runtime.capture_deployment_inventory,
            self.config.backup_path,
        )
        cosmos_mutated = False
        try:
            deployment = self._call(
                "deploy_existing_topology", self.runtime.deploy_existing_topology
            )
            cosmos_mutated = True
            reset = self._call("reset", self.runtime.reset)
            direct = self._call("direct_snapshot", self.runtime.direct_snapshot)
            baseline = validate_baseline_snapshot(direct)
            mirror = self._call(
                "mirror_poll",
                self.runtime.poll_mirror,
                {
                    "mode": "baseline",
                    "counts": BASELINE_COUNTS,
                    "stale_derived_rows_deleted": True,
                },
                self.config.timeout_seconds,
            )
            power_bi = self._call(
                "power_bi_baseline", self.runtime.verify_power_bi_baseline, TENANTS
            )
            self._check_head()
        except Exception as original:
            deployment_mutated = self.runtime.deployment_mutated()
            if not cosmos_mutated and not deployment_mutated:
                raise
            rollback: dict[str, Any] = {}
            if cosmos_mutated:
                try:
                    rollback["cosmos"] = self._call(
                        "rollback_cosmos", self.runtime.restore, self.config.backup_path
                    )
                except Exception as exc:
                    rollback["cosmos"] = {"status": "FAIL", "error": str(exc)}
            if deployment_mutated:
                try:
                    rollback["deployment"] = self._call(
                        "rollback_deployment", self.runtime.rollback_deployment, inventory
                    )
                except Exception as exc:
                    rollback["deployment"] = {"status": "FAIL", "error": str(exc)}
            rollback_ok = all(
                result.get("status") == "PASS" for result in rollback.values()
            )
            raise VerificationError(
                f"baseline-live failed: {original}; rollback_status="
                f"{'PASS' if rollback_ok else 'FAIL'}; rollback={rollback}"
            ) from original
        forbidden = FORBIDDEN_BASELINE_OPERATIONS.intersection(self.events)
        if forbidden:
            raise VerificationError(
                f"baseline-live executed forbidden operations: {sorted(forbidden)}"
            )
        return self._result(
            {
                "identity": identity,
                "backup": backup,
                "rollback_targets": inventory,
                "deployment": deployment,
                "reset": reset,
                "baseline": baseline,
                "mirror": mirror,
                "power_bi": power_bi,
            }
        )

    def _post_traffic(self, identity: dict[str, Any]) -> dict[str, Any]:
        direct = self._call("direct_snapshot", self.runtime.direct_snapshot)
        payload: dict[str, Any] = {
            "identity": identity,
            "direct": summarize_snapshot(direct),
        }
        if self.config.recompute == "in-process":
            payload["recompute"] = self._call(
                "recompute_in_process", self.runtime.recompute_in_process
            )
        elif self.config.recompute == "fabric":
            payload["controller"] = self._call(
                "fabric_controller", self.runtime.run_fabric_controller
            )
            payload["mirror"] = self._call(
                "mirror_poll",
                self.runtime.poll_mirror,
                {"mode": "post-traffic", "stale_derived_rows_deleted": True},
                self.config.timeout_seconds,
            )
        if {"apply", "traffic"}.intersection(self.events):
            raise VerificationError("post-traffic must never Apply or generate traffic")
        self._check_head()
        return self._result(payload)

    def _local_simulation(self, identity: dict[str, Any]) -> dict[str, Any]:
        direct = self._call("direct_snapshot", self.runtime.direct_snapshot)
        self._check_head()
        return self._result(
            {"identity": identity, "baseline": validate_baseline_snapshot(direct)}
        )

    def _result(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "PASS",
            "mode": self.config.mode,
            "recompute": self.config.recompute,
            "events": self.events,
            **payload,
        }
