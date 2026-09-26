#!/usr/bin/env python3
"""Fabric auto-provisioning orchestrator for the Travel Assistant optimization analytics.

Given a deployed Fabric **capacity** (created by infra/shared/fabriccapacity.bicep when
deployAnalytics=true), this script provisions the rest of the analytics pipeline via the
Fabric + Power BI + Azure REST APIs:

  Phase 1 (fully automated):
    - create a NEW workspace (not the default) and assign it to the F2 capacity
    - provision the workspace identity
    - grant the workspace identity Cosmos RBAC (custom mirroring role + Data Contributor)
    - enable the Cosmos network-ACL bypass for the workspace

  Phase 2 (needs the manual OAuth2 Cosmos connection — the one un-automatable step):
    - (interactive) you create the Cosmos connection once in the Fabric portal and paste
      its id (WorkspaceIdentity connections are still DMTS-blocked in many tenants)
    - create the mirrored database (OptimizationTurns / NodeExecutions / Trips / OptimizationPolicies /
      OptimizationGovernance / Configuration / Messages / ApiEvents / OptimizationInsights / memories) + start
    - upload the reverse-ETL notebook (Module 09) with its parameters pre-filled
      (Cosmos + mirror SQL endpoint). The report uses DirectQuery over the mirror SQL
      endpoint, so no separate Direct Lake semantic model is created.
    - create/update a Data Pipeline controller that runs Analytics first (including
      shared global work), then Marvel (tenant work only)
    - deploy the translytical Apply/Revert User Data Function (Cosmos endpoint injected,
      azure-cosmos installed) + grant the deploying user Cosmos data-plane write, so
      Power BI buttons drive the optimization apply-loop with no manual portal steps

  Phase 3:
    - deploy the source-controlled TMDL semantic model and PBIR report, hydrate their
      deployment placeholders, bind the DirectQuery source for SSO, and verify the model
      queries — so deploying the report needs no Power BI Desktop

Auth uses your `az login` (DefaultAzureCredential). Config is read from `azd env get-values`
by default; override with CLI flags. Idempotent: existing workspace/mirror/etc. are reused.

See analytics/fabric/README.md for the proven REST payloads this automates.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from fabric_assets import (
    PIPELINE_DISPLAY_NAME,
    demo_tenant_pipeline_definition,
    validate_demo_tenant_pipeline_definition,
)

try:
    from azure.identity import DefaultAzureCredential
except ImportError:  # pragma: no cover - staging preflight remains usable without Azure SDK
    DefaultAzureCredential = None

FABRIC_API = "https://api.fabric.microsoft.com/v1"
PBI_API = "https://api.powerbi.com/v1.0/myorg"
ARM_API = "https://management.azure.com"

FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
PBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
ARM_SCOPE = "https://management.azure.com/.default"

# Cosmos built-in Data Contributor data-plane role definition id (fixed GUID).
COSMOS_DATA_CONTRIBUTOR = "00000000-0000-0000-0000-000000000002"

# Tables to mirror (schema name == Cosmos DB name; set at runtime).
# `memories` powers the Memory Intelligence report page (salience / health / supersession).
MIRROR_TABLES = ["OptimizationTurns", "NodeExecutions", "Trips", "OptimizationPolicies", "OptimizationGovernance", "Configuration", "Messages", "ApiEvents", "OptimizationInsights", "memories"]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EVIDENCE: dict[str, Any] = {}
ACTIVE_ARGS: argparse.Namespace | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tree_sha256(path: Path) -> str:
    if not path.is_dir():
        raise FileNotFoundError(f"source definition directory not found: {path}")
    digest = hashlib.sha256()
    files = sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
    if not files:
        raise FileNotFoundError(f"source definition directory is empty: {path}")
    for item in files:
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _source_hashes(args: argparse.Namespace) -> dict[str, str]:
    notebook = Path(args.notebook)
    if args.solution and not notebook.stem.endswith("_solution"):
        notebook = notebook.with_name(f"{notebook.stem}_solution{notebook.suffix}")
    sources = {
        "notebook": hashlib.sha256(notebook.read_bytes()).hexdigest(),
        "pipeline": hashlib.sha256(
            json.dumps(
                demo_tenant_pipeline_definition(
                    "{{FABRIC_WORKSPACE_ID}}", "{{FABRIC_NOTEBOOK_ID}}"
                ),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "udf": _tree_sha256(HERE / "udf"),
        "semantic_model": _tree_sha256(Path(args.semantic_model_source)),
        "report": _tree_sha256(Path(args.report_source)),
    }
    return sources


def _initialize_evidence(args: argparse.Namespace) -> None:
    global EVIDENCE
    EVIDENCE = {
        "schema_version": 1,
        "status": "Unverified",
        "environment": args.environment,
        "started_utc": _utc_now(),
        "completed_utc": None,
        "reason": "",
        "ids": {
            "workspace": None,
            "mirror": None,
            "notebook": None,
            "pipeline": None,
            "udf": None,
            "semantic_model": None,
            "report": None,
        },
        "source_definition_hashes": {},
        "query_evidence": {"semantic_model": None, "report": None},
    }
    EVIDENCE["source_definition_hashes"] = _source_hashes(args)


def _write_evidence(args: argparse.Namespace, status: str, reason: str = "") -> None:
    EVIDENCE["status"] = status
    EVIDENCE["reason"] = reason
    EVIDENCE["completed_utc"] = _utc_now()
    path = Path(args.evidence_output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(EVIDENCE, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"FABRIC_STAGING_EVIDENCE={path}")
    print(f"FABRIC_STAGING_STATUS={status}")


def _record_ids(**ids: str | None) -> None:
    for key, value in ids.items():
        if value:
            EVIDENCE["ids"][key] = value


# --------------------------------------------------------------------------- creds
class Tokens:
    """Lazily cached tokens, preferring the active Azure PowerShell context on Windows."""

    def __init__(self) -> None:
        if DefaultAzureCredential is None:
            raise RuntimeError(
                "azure-identity is unavailable; install deployment dependencies before provisioning"
            )
        self._cred = DefaultAzureCredential(exclude_interactive_browser_credential=False)
        self._cache: dict[str, tuple[str, float]] = {}

    @staticmethod
    def _powershell(scope: str) -> tuple[str, float]:
        resource = scope[: -len(".default")] if scope.endswith("/.default") else scope
        escaped = resource.replace("'", "''")
        script = (
            f"$r=Get-AzAccessToken -ResourceUrl '{escaped}';"
            "if($r.Token -is [securestring]){"
            "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($r.Token);"
            "try{$token=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p)}"
            "finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}}"
            "else{$token=$r.Token};"
            "[ordered]@{token=$token;expiresOn=$r.ExpiresOn.ToUnixTimeSeconds()}|"
            "ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode or not completed.stdout.strip():
            raise RuntimeError(completed.stderr.strip() or "Get-AzAccessToken failed")
        payload = json.loads(completed.stdout)
        return payload["token"], float(payload["expiresOn"])

    def get(self, scope: str) -> str:
        tok, exp = self._cache.get(scope, (None, 0.0))
        if tok and time.time() < exp - 120:
            return tok
        if os.name == "nt":
            try:
                tok, exp = self._powershell(scope)
                self._cache[scope] = (tok, exp)
                return tok
            except Exception as exc:
                log(
                    f"Azure PowerShell token unavailable for {scope}; "
                    f"using safe fallback ({type(exc).__name__})"
                )
        token = self._cred.get_token(scope)
        self._cache[scope] = (token.token, token.expires_on)
        return token.token

    def headers(self, scope: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get(scope)}", "Content-Type": "application/json"}


# --------------------------------------------------------------------------- helpers
def log(msg: str) -> None:
    print(f"[fabric] {msg}", flush=True)


def die(msg: str) -> "None":
    print(f"[fabric] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def b64(obj: Any) -> str:
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


def req(
    method: str,
    url: str,
    headers: dict,
    *,
    json_body: Any = None,
    ok=(200, 201, 202),
    retry_safe: bool = False,
) -> requests.Response:
    method = method.upper()
    retry_safe = retry_safe or method in {"GET", "PUT", "PATCH", "DELETE"}
    attempts = 4 if retry_safe else 1
    for attempt in range(1, attempts + 1):
        try:
            r = requests.request(
                method, url, headers=headers, json=json_body, timeout=120
            )
        except (requests.ConnectionError, requests.Timeout):
            if attempt == attempts:
                raise
            time.sleep(min(2 ** (attempt - 1), 8))
            continue
        if r.status_code in ok:
            return r
        if (
            retry_safe
            and r.status_code in {408, 429, 500, 502, 503, 504}
            and attempt < attempts
        ):
            retry_after = r.headers.get("Retry-After", "")
            delay = int(retry_after) if retry_after.isdigit() else min(2 ** (attempt - 1), 8)
            time.sleep(delay)
            continue
        raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text[:600]}")
    raise AssertionError("Fabric request retry loop exited unexpectedly")


def poll_lro(resp: requests.Response, headers: dict, timeout: int = 600) -> Optional[dict]:
    """Follow a Fabric long-running-operation (202 + Location header) to completion."""
    if resp.status_code != 202:
        return resp.json() if resp.text else None
    loc = resp.headers.get("Location")
    if not loc:
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(int(resp.headers.get("Retry-After", "5")))
        s = req("GET", loc, headers, ok=(200, 202))
        status = s.json().get("status") if s.text else None
        if status in ("Succeeded", "Completed"):
            result_url = s.headers.get("Location")
            if result_url:
                rr = req("GET", result_url, headers, ok=(200, 202))
                return rr.json() if rr.text else None
            return s.json()
        if status in ("Failed", "Cancelled"):
            raise RuntimeError(f"LRO failed: {s.text[:600]}")
    raise TimeoutError("LRO timed out")


def az(args: list[str]) -> str:
    exe = "az.cmd" if os.name == "nt" else "az"
    r = subprocess.run([exe, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"az {' '.join(args)} failed: {r.stderr.strip()[:500]}")
    return r.stdout.strip()


def azure_context() -> dict[str, str]:
    """Resolve subscription and tenant without relying on the Azure CLI cache."""
    if os.name == "nt":
        script = (
            "$c=Get-AzContext;"
            "if($null -eq $c){exit 1};"
            "[ordered]@{subscription=$c.Subscription.Id;tenant=$c.Tenant.Id}|"
            "ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return json.loads(completed.stdout)
    return {
        "subscription": az(["account", "show", "--query", "id", "-o", "tsv"]),
        "tenant": az(["account", "show", "--query", "tenantId", "-o", "tsv"]),
    }


def load_azd_env() -> dict[str, str]:
    try:
        out = subprocess.run(
            ["azd", "env", "get-values"], capture_output=True, text=True, cwd=os.getcwd()
        )
        if out.returncode != 0:
            return {}
        env: dict[str, str] = {}
        for line in out.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"')
        return env
    except FileNotFoundError:
        return {}


def persist_env(updates: dict[str, str]) -> None:
    """Persist ids to the azd env and to ./python/.env so the console picks them up."""
    for k, v in updates.items():
        if not v:
            continue
        try:
            subprocess.run(["azd", "env", "set", k, v], capture_output=True, text=True)
        except FileNotFoundError:
            pass
    env_path = os.path.join(os.getcwd(), "python", ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        keys = {k for k, v in updates.items() if v}
        kept = [ln for ln in lines if ln.split("=", 1)[0].strip() not in keys]
        for k, v in updates.items():
            if v:
                kept.append(f'{k}="{v}"\n')
        with open(env_path, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(kept)
        log(f"persisted {list(updates)} to {env_path}")
    except OSError as e:
        log(f"could not update {env_path}: {e}")


# --------------------------------------------------------------------------- phase 1
def wait_for_capacity(tok: Tokens, capacity_name: str, timeout: int = 2400) -> str:
    """Return the Fabric capacity GUID once the ARM capacity has synced to Fabric.

    Newly ARM-created Fabric capacities can take a long time (observed 25+ minutes in
    some tenants) to propagate into the Fabric control plane even though ARM already
    reports them Active, so this waits generously.
    """
    log(f"waiting for capacity '{capacity_name}' to appear in Fabric control plane "
        f"(ARM-created capacities can take 20-40 min to propagate)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = req("GET", f"{FABRIC_API}/capacities", tok.headers(FABRIC_SCOPE))
        for c in r.json().get("value", []):
            if c.get("displayName", "").lower() == capacity_name.lower():
                if c.get("state") == "Active":
                    log(f"capacity ready: {c['id']} ({c.get('sku')}, {c.get('state')})")
                    return c["id"]
                log(f"capacity found, state={c.get('state')} (waiting for Active)")
        time.sleep(20)
    die(
        f"capacity '{capacity_name}' did not become Active in the Fabric control plane "
        f"within {timeout}s. If Azure Resource Manager reports it Active but Fabric does "
        "not list it, the saved FABRIC_CAPACITY_LOCATION may not be available for this "
        "tenant. Set that azd value to a supported Fabric region, reprovision the capacity, "
        "and retry."
    )
    return ""  # unreachable


def get_or_create_workspace(tok: Tokens, name: str, capacity_id: str) -> str:
    r = req("GET", f"{FABRIC_API}/workspaces", tok.headers(FABRIC_SCOPE))
    for w in r.json().get("value", []):
        if w.get("displayName") == name:
            log(f"workspace exists: {w['id']}")
            ws_id = w["id"]
            break
    else:
        log(f"creating workspace '{name}'...")
        try:
            c = req(
                "POST",
                f"{FABRIC_API}/workspaces",
                tok.headers(FABRIC_SCOPE),
                json_body={"displayName": name, "description": "Travel Assistant optimization analytics"},
            )
        except RuntimeError as exc:
            if "WorkspaceNameAlreadyExists" in str(exc):
                raise RuntimeError(
                    f"Fabric workspace name '{name}' is already reserved in this tenant but "
                    "is not visible to the signed-in user. Re-run with a unique --workspace "
                    "value, for example 'Multi-Agent Travel Workshop <your initials>'."
                ) from exc
            raise
        ws_id = c.json()["id"]
        log(f"workspace created: {ws_id}")

    log(f"assigning workspace to capacity {capacity_id}...")
    req(
        "POST",
        f"{FABRIC_API}/workspaces/{ws_id}/assignToCapacity",
        tok.headers(FABRIC_SCOPE),
        json_body={"capacityId": capacity_id},
        ok=(200, 202),
    )
    return ws_id


def provision_workspace_identity(tok: Tokens, ws_id: str) -> Optional[str]:
    """Provision the workspace identity; return its service-principal object id."""
    hdr = tok.headers(FABRIC_SCOPE)
    try:
        resp = req("POST", f"{FABRIC_API}/workspaces/{ws_id}/provisionIdentity", hdr, ok=(200, 202))
        poll_lro(resp, hdr)
        log("workspace identity provisioned")
    except RuntimeError as e:
        if "already" in str(e).lower() or "conflict" in str(e).lower():
            log("workspace identity already present")
        else:
            raise
    w = req("GET", f"{FABRIC_API}/workspaces/{ws_id}", hdr).json()
    sp = (w.get("workspaceIdentity") or {}).get("servicePrincipalId")
    log(f"workspace identity SP: {sp}")
    return sp


def _wait_for_sp_in_aad(sp_object_id: str, timeout: int = 300) -> bool:
    """Wait for a newly-provisioned workspace-identity SP to be queryable in AAD.

    Fabric provisions the identity immediately but its AAD service principal takes a
    minute or two to propagate; Cosmos RBAC assignment fails with 'not found in the AAD
    tenant' until it does.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        exe = "az.cmd" if os.name == "nt" else "az"
        r = subprocess.run(
            [exe, "ad", "sp", "show", "--id", sp_object_id, "--query", "id", "-o", "tsv"],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return True
        log("waiting for workspace-identity SP to propagate to AAD...")
        time.sleep(15)
    return False


def _current_user_object_id() -> Optional[str]:
    exe = "az.cmd" if os.name == "nt" else "az"
    r = subprocess.run(
        [exe, "ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def ensure_fabric_mirroring_role(cosmos_account: str, rg: str, account_scope: str) -> str:
    """Return the id of a custom Cosmos role granting readMetadata + readAnalytics,
    creating it if it doesn't already exist. Fabric mirroring's analytical snapshot read
    requires readAnalytics, which the built-in Data Contributor role does NOT include."""
    wanted = {
        "Microsoft.DocumentDB/databaseAccounts/readMetadata",
        "Microsoft.DocumentDB/databaseAccounts/readAnalytics",
    }
    defs = json.loads(
        az(["cosmosdb", "sql", "role", "definition", "list", "-a", cosmos_account, "-g", rg, "-o", "json"])
        or "[]"
    )
    for d in defs:
        perms = d.get("permissions") or []
        actions = set(perms[0].get("dataActions", [])) if perms else set()
        if wanted <= actions:
            return d["id"].split("/sqlRoleDefinitions/")[-1]
    log("creating custom FabricMirroringRole (readMetadata + readAnalytics)...")
    body = {
        "RoleName": "FabricMirroringRole",
        "Type": "CustomRole",
        "AssignableScopes": [account_scope],
        "Permissions": [{"DataActions": sorted(wanted)}],
    }
    bf = os.path.join(os.getenv("TEMP", "/tmp"), "fabric_role.json")
    with open(bf, "w", encoding="utf-8") as f:
        json.dump(body, f)
    out = az(["cosmosdb", "sql", "role", "definition", "create", "-a", cosmos_account, "-g", rg,
              "--body", f"@{bf}", "-o", "json"])
    return json.loads(out)["id"].split("/sqlRoleDefinitions/")[-1]


def _assign_role(cosmos_account: str, rg: str, account_scope: str, role_id: str,
                 principal_id: str, existing: list, label: str) -> None:
    for a in existing:
        props = a.get("properties", a)
        if props.get("principalId") == principal_id and props.get("roleDefinitionId", "").endswith(role_id):
            log(f"role already assigned to {label}")
            return
    log(f"assigning FabricMirroringRole to {label} ({principal_id})...")
    az(["cosmosdb", "sql", "role", "assignment", "create", "-a", cosmos_account, "-g", rg,
        "--role-definition-id", role_id, "--principal-id", principal_id, "--scope", account_scope])


def grant_cosmos_rbac(cosmos_account: str, rg: str, sub: str, sp_object_id: str,
                      app_identity_oid: str = "") -> None:
    """Grant Cosmos readMetadata + readAnalytics to every identity that may drive mirroring.

    Fabric mirroring reads Cosmos through the connection. With an OAuth2 connection that
    identity is the **deploying user**; with a (future) WorkspaceIdentity or service-
    principal connection it is the **workspace identity SP** or the **app's managed
    identity**. All need readAnalytics (built-in Data Contributor is NOT enough), so we
    grant a custom FabricMirroringRole to: the deploying user (the identity that matters
    today), the app's managed identity, and the workspace identity SP (future paths).
    """
    account_scope = (
        f"/subscriptions/{sub}/resourceGroups/{rg}/providers/"
        f"Microsoft.DocumentDB/databaseAccounts/{cosmos_account}"
    )
    role_id = ensure_fabric_mirroring_role(cosmos_account, rg, account_scope)
    existing = json.loads(
        az(["cosmosdb", "sql", "role", "assignment", "list", "-a", cosmos_account, "-g", rg, "-o", "json"])
        or "[]"
    )
    user_oid = _current_user_object_id()
    if user_oid:
        _assign_role(cosmos_account, rg, account_scope, role_id, user_oid, existing,
                     "the deploying user (OAuth2 connection identity)")
    else:
        log("WARNING: could not resolve the signed-in user object id; the OAuth2 mirror "
            "connection needs readAnalytics on this account.")
    if app_identity_oid:
        _assign_role(cosmos_account, rg, account_scope, role_id, app_identity_oid, existing,
                     "the app managed identity")
    if sp_object_id and _wait_for_sp_in_aad(sp_object_id):
        _assign_role(cosmos_account, rg, account_scope, role_id, sp_object_id, existing,
                     "the workspace identity SP")


def enable_cosmos_bypass(cosmos_account: str, rg: str, tenant_id: str, ws_id: str) -> None:
    """Configure the Cosmos network trust needed for Fabric mirroring.

    The ``networkAclBypass`` allowlist is a **private-endpoint / restricted-network**
    feature: it lets an allowlisted Fabric workspace bypass the account's network ACLs.
    On a **public** account (``publicNetworkAccess=Enabled``, the workshop default) it is
    unnecessary and actively harmful — setting ``networkAclBypass=AzureServices`` puts a
    public account into a mode that *blocks* the mirroring snapshot service (observed:
    'status code 0, account doesn't exist'). So we only apply the bypass when the account
    is not publicly reachable; for public accounts we leave the network config alone.
    """
    info = json.loads(
        az(["cosmosdb", "show", "-n", cosmos_account, "-g", rg,
            "--query", "{public:publicNetworkAccess}", "-o", "json"]) or "{}"
    )
    if (info.get("public") or "Enabled") == "Enabled":
        log("Cosmos account is public (publicNetworkAccess=Enabled); skipping the "
            "networkAclBypass (it is a private-endpoint feature and would block mirroring).")
        return
    bypass_id = (
        f"/tenants/{tenant_id}/subscriptions/00000000-0000-0000-0000-000000000000/"
        f"resourceGroups/Fabric/providers/Microsoft.Fabric/workspaces/{ws_id}"
    )
    caps = json.loads(
        az(["cosmosdb", "show", "-n", cosmos_account, "-g", rg, "--query", "capabilities", "-o", "json"])
        or "[]"
    )
    names = {c.get("name") for c in caps}
    names.add("EnableFabricNetworkAclBypass")
    log("restricted-network account: enabling Cosmos network-ACL bypass for the workspace...")
    az(
        [
            "cosmosdb", "update", "-n", cosmos_account, "-g", rg,
            "--capabilities", *sorted(n for n in names if n),
            "--network-acl-bypass", "AzureServices",
            "--network-acl-bypass-resource-ids", bypass_id,
        ]
    )
    log("Cosmos network bypass configured")


# --------------------------------------------------------------------------- phase 2
def get_or_create_mirror(tok: Tokens, ws_id: str, connection_id: str, db_name: str) -> str:
    hdr = tok.headers(FABRIC_SCOPE)
    name = f"{db_name}Analytics"
    r = req("GET", f"{FABRIC_API}/workspaces/{ws_id}/mirroredDatabases", hdr)
    for m in r.json().get("value", []):
        if m.get("displayName") == name:
            log(f"mirror exists: {m['id']}")
            changed = update_mirror_tables(tok, ws_id, m["id"], db_name)
            if changed:
                # A running Cosmos mirror only picks up newly-mounted tables after a
                # stop/start cycle, so restart when we actually added tables.
                _restart_mirroring(tok, ws_id, m["id"])
            else:
                _start_mirroring_when_ready(tok, ws_id, m["id"])
            return m["id"]
    mirroring = {
        "properties": {
            "source": {
                "type": "CosmosDb",
                "typeProperties": {"connection": connection_id, "database": db_name},
            },
            "target": {
                "type": "MountedRelationalDatabase",
                "typeProperties": {"defaultSchema": "dbo", "format": "Delta"},
            },
            "mountedTables": [
                {"source": {"typeProperties": {"schemaName": db_name, "tableName": t}}}
                for t in MIRROR_TABLES
            ],
        }
    }
    body = {
        "displayName": name,
        "definition": {
            "parts": [
                {"path": "mirroring.json", "payload": b64(mirroring), "payloadType": "InlineBase64"}
            ]
        },
    }
    log(f"creating mirrored database '{name}'...")
    resp = req("POST", f"{FABRIC_API}/workspaces/{ws_id}/mirroredDatabases", hdr, json_body=body, ok=(200, 201, 202))
    result = poll_lro(resp, hdr) or resp.json()
    mid = result["id"]
    log(f"mirror created: {mid}; waiting for it to initialize before starting...")
    _start_mirroring_when_ready(tok, ws_id, mid)
    return mid


def update_mirror_tables(tok: Tokens, ws_id: str, mid: str, db_name: str) -> bool:
    """Add any MIRROR_TABLES missing from an existing mirror's definition.

    Fetches the current mirroring.json, appends tables not already mounted, and
    calls updateDefinition (preserving the other definition parts, e.g. .platform).
    A running Cosmos mirror picks the new tables up and begins replicating them;
    if it was stopped, the caller's _start_mirroring_when_ready restarts it.
    Returns True if the definition was changed.
    """
    hdr = tok.headers(FABRIC_SCOPE)
    resp = req("POST", f"{FABRIC_API}/workspaces/{ws_id}/mirroredDatabases/{mid}/getDefinition",
               hdr, json_body={}, ok=(200, 202), retry_safe=True)
    res = poll_lro(resp, hdr) or (resp.json() if resp.text else {})
    parts = res.get("definition", {}).get("parts", [])
    part = next((p for p in parts if p.get("path") == "mirroring.json"), None)
    if part is None:
        log("mirror has no mirroring.json part; cannot update tables")
        return False

    mirroring = json.loads(base64.b64decode(part["payload"]).decode("utf-8"))
    mounted = mirroring["properties"].setdefault("mountedTables", [])
    current = {t.get("source", {}).get("typeProperties", {}).get("tableName") for t in mounted}
    missing = [t for t in MIRROR_TABLES if t not in current]
    if not missing:
        log(f"mirror tables up to date ({', '.join(sorted(current))})")
        return False

    for t in missing:
        mounted.append({"source": {"typeProperties": {"schemaName": db_name, "tableName": t}}})
    part["payload"] = b64(mirroring)

    log(f"adding table(s) to mirror: {', '.join(missing)}")
    r = req("POST", f"{FABRIC_API}/workspaces/{ws_id}/mirroredDatabases/{mid}/updateDefinition",
            hdr, json_body={"definition": {"parts": parts}}, ok=(200, 202), retry_safe=True)
    poll_lro(r, hdr)
    log("mirror definition updated")
    return True


def _restart_mirroring(tok: Tokens, ws_id: str, mid: str, timeout: int = 300) -> None:
    """Stop then start mirroring so a running mirror picks up newly-mounted tables."""
    hdr = tok.headers(FABRIC_SCOPE)
    base = f"{FABRIC_API}/workspaces/{ws_id}/mirroredDatabases/{mid}"
    status = (req("POST", f"{base}/getMirroringStatus", hdr, json_body={}, ok=(200,)).json() or {}).get("status")
    if status in ("Running", "Starting"):
        log("stopping mirroring to pick up new tables...")
        req("POST", f"{base}/stopMirroring", hdr, ok=(200, 202))
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = (req("POST", f"{base}/getMirroringStatus", hdr, json_body={}, ok=(200,)).json() or {}).get("status")
            if status in ("Stopped", "Initialized"):
                break
            log(f"mirror status={status}; waiting to stop...")
            time.sleep(10)
    _start_mirroring_when_ready(tok, ws_id, mid, timeout)


def _start_mirroring_when_ready(tok: Tokens, ws_id: str, mid: str, timeout: int = 300) -> None:
    """A freshly-created mirror is 'Initializing'; startMirroring is only valid once it
    reaches 'Initialized'/'Stopped'. Poll, then start (skip if already running)."""
    hdr = tok.headers(FABRIC_SCOPE)
    status_url = f"{FABRIC_API}/workspaces/{ws_id}/mirroredDatabases/{mid}/getMirroringStatus"
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = (req("POST", status_url, hdr, json_body={}, ok=(200,)).json() or {}).get("status")
        if status in ("Running", "Starting"):
            log(f"mirroring already {status}")
            return
        if status in ("Initialized", "Stopped"):
            log(f"mirror {status}; starting mirroring...")
            req("POST", f"{FABRIC_API}/workspaces/{ws_id}/mirroredDatabases/{mid}/startMirroring",
                hdr, ok=(200, 202))
            return
        log(f"mirror status={status}; waiting...")
        time.sleep(10)
    raise TimeoutError(f"mirror {mid} did not become ready to start within {timeout}s")


def get_mirror_sql_endpoint(tok: Tokens, ws_id: str, mid: str) -> str:
    """The mirror's SQL analytics endpoint host (for the notebook / report params)."""
    hdr = tok.headers(FABRIC_SCOPE)
    r = req("GET", f"{FABRIC_API}/workspaces/{ws_id}/mirroredDatabases/{mid}", hdr)
    props = r.json().get("properties", {})
    return (props.get("sqlEndpointProperties", {}) or {}).get("connectionString", "")


def upload_notebook(tok: Tokens, ws_id: str, nb_path: str, params: dict[str, str]) -> Optional[str]:
    hdr = tok.headers(FABRIC_SCOPE)
    if not os.path.exists(nb_path):
        log(f"notebook not found at {nb_path}; skipping")
        return None
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)
    # inject parameter values into the `parameters`-tagged cell
    for cell in nb.get("cells", []):
        if "parameters" in (cell.get("metadata", {}).get("tags") or []):
            header = [f"{k} = {json.dumps(v)}\n" for k, v in params.items()]
            cell["source"] = header + ["\n"] + [
                ln for ln in cell.get("source", []) if not any(ln.startswith(f"{k} ") for k in params)
            ]
            break
    payload = b64(nb)
    # Fabric display name derived from the file (the learner TODO and the _solution
    # variant both land as the same notebook "ConversionFunnelReverseETL").
    name = os.path.splitext(os.path.basename(nb_path))[0].replace("_solution", "")
    r = req("GET", f"{FABRIC_API}/workspaces/{ws_id}/notebooks", hdr)
    existing = next((n for n in r.json().get("value", []) if n.get("displayName") == name), None)
    body = {
        "displayName": name,
        "definition": {
            "format": "ipynb",
            "parts": [{"path": "notebook-content.ipynb", "payload": payload, "payloadType": "InlineBase64"}],
        },
    }
    if existing:
        log("updating existing notebook definition...")
        req(
            "POST",
            f"{FABRIC_API}/workspaces/{ws_id}/notebooks/{existing['id']}/updateDefinition",
            hdr,
            json_body={"definition": body["definition"]},
            ok=(200, 202),
            retry_safe=True,
        )
        return existing["id"]
    log("creating notebook...")
    resp = req("POST", f"{FABRIC_API}/workspaces/{ws_id}/notebooks", hdr, json_body=body, ok=(200, 201, 202))
    result = poll_lro(resp, hdr) or resp.json()
    return result.get("id")


def provision_demo_tenant_pipeline(tok: Tokens, ws_id: str, notebook_id: str) -> str:
    """Create/update the sequential two-tenant notebook controller."""
    hdr = tok.headers(FABRIC_SCOPE)
    definition = demo_tenant_pipeline_definition(ws_id, notebook_id)
    validate_demo_tenant_pipeline_definition(definition, ws_id, notebook_id)
    definition_part = {
        "path": "pipeline-content.json",
        "payload": b64(definition),
        "payloadType": "InlineBase64",
    }
    items = req("GET", f"{FABRIC_API}/workspaces/{ws_id}/dataPipelines", hdr).json().get("value", [])
    existing = next((p for p in items if p.get("displayName") == PIPELINE_DISPLAY_NAME), None)
    if existing:
        log(f"updating demo-tenant pipeline '{PIPELINE_DISPLAY_NAME}'...")
        resp = req(
            "POST",
            f"{FABRIC_API}/workspaces/{ws_id}/dataPipelines/{existing['id']}/updateDefinition",
            hdr,
            json_body={"definition": {"parts": [definition_part]}},
            ok=(200, 202),
            retry_safe=True,
        )
        poll_lro(resp, hdr)
        return existing["id"]

    log(f"creating demo-tenant pipeline '{PIPELINE_DISPLAY_NAME}'...")
    resp = req(
        "POST",
        f"{FABRIC_API}/workspaces/{ws_id}/dataPipelines",
        hdr,
        json_body={
            "displayName": PIPELINE_DISPLAY_NAME,
            "description": "Sequential refresh for the Analytics and Marvel demo tenants",
            "definition": {"parts": [definition_part]},
        },
        ok=(200, 201, 202),
    )
    result = poll_lro(resp, hdr) or (resp.json() if resp.text else {})
    pipeline_id = result.get("id")
    if not pipeline_id:
        raise RuntimeError("Fabric did not return an id for the demo-tenant pipeline")
    return pipeline_id


def deploy_udf(tok: Tokens, ws_id: str, udf_src_path: str, cosmos_endpoint: str, db_name: str,
               display_name: str = "optimization-apply-loop") -> Optional[str]:
    """Create/update the translytical Apply/Revert User Data Function.

    Uploads function_app.py (with this deployment's Cosmos endpoint + database
    injected) plus the azure-cosmos library dependency, so students and demo users
    get a working Apply/Revert UDF with no manual portal steps. The functions flip
    an OptimizationPolicies doc via Fabric's managed CosmosDB connection; a Power BI
    translytical button binds straight to them.
    """
    hdr = tok.headers(FABRIC_SCOPE)
    if not os.path.exists(udf_src_path):
        log(f"UDF source not found at {udf_src_path}; skipping UDF deploy")
        return None
    with open(udf_src_path, "r", encoding="utf-8") as f:
        code = f.read()
    # inject the deployment's Cosmos endpoint + database into the two config constants
    code = re.sub(r'COSMOS_URI = ".*?"', f'COSMOS_URI = "{cosmos_endpoint}"', code, count=1)
    code = re.sub(r'DB_NAME = ".*?"', f'DB_NAME = "{db_name}"', code, count=1)

    definition = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/userDataFunction/definition/1.1.0/schema.json",
        "runtime": "PYTHON",
        "connectedDataSources": [],
        "functions": [
            {"name": "apply_optimization", "description": "", "isPublicEndpointEnabled": True},
            {"name": "revert_optimization", "description": "", "isPublicEndpointEnabled": True},
            {"name": "get_optimization_status", "description": "", "isPublicEndpointEnabled": True},
        ],
        "libraries": {
            "public": [
                {"name": "azure-cosmos", "type": "PYPI", "version": "4.16.3"},
                {"name": "fabric-user-data-functions", "type": "PYPI", "version": "1.0"},
            ],
            "private": [],
        },
    }
    platform = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "UserDataFunction", "displayName": display_name},
        "config": {"version": "2.0", "logicalId": "00000000-0000-0000-0000-000000000000"},
    }
    parts = [
        {"path": "definition.json", "payload": b64(definition), "payloadType": "InlineBase64"},
        {"path": "function_app.py",
         "payload": base64.b64encode(code.encode("utf-8")).decode("ascii"),
         "payloadType": "InlineBase64"},
        {"path": ".platform", "payload": b64(platform), "payloadType": "InlineBase64"},
    ]
    body = {"displayName": display_name, "definition": {"parts": parts}}

    r = req("GET", f"{FABRIC_API}/workspaces/{ws_id}/userDataFunctions", hdr)
    existing = next((u for u in r.json().get("value", []) if u.get("displayName") == display_name), None)
    if existing:
        log("updating existing User Data Function definition...")
        resp = req("POST",
                   f"{FABRIC_API}/workspaces/{ws_id}/userDataFunctions/{existing['id']}/updateDefinition",
                   hdr, json_body={"definition": body["definition"]}, ok=(200, 202),
                   retry_safe=True)
        poll_lro(resp, hdr)
        udf_id = existing["id"]
    else:
        log("creating User Data Function...")
        resp = req("POST", f"{FABRIC_API}/workspaces/{ws_id}/userDataFunctions", hdr,
                   json_body=body, ok=(200, 201, 202))
        result = poll_lro(resp, hdr) or resp.json()
        udf_id = result.get("id")
    log(f"User Data Function ready (id {udf_id})")
    return udf_id


def grant_cosmos_data_contributor(cosmos_account: str, rg: str, sub: str) -> None:
    """Grant the signed-in user Cosmos Built-in Data Contributor (data-plane read+write)
    so the translytical UDF can flip OptimizationPolicies on their behalf."""
    user_oid = _current_user_object_id()
    if not user_oid:
        log("WARNING: could not resolve the signed-in user; grant Cosmos Data Contributor "
            "manually so the Apply/Revert UDF can write policies.")
        return
    account_scope = (
        f"/subscriptions/{sub}/resourceGroups/{rg}/providers/"
        f"Microsoft.DocumentDB/databaseAccounts/{cosmos_account}"
    )
    existing = json.loads(
        az(["cosmosdb", "sql", "role", "assignment", "list", "-a", cosmos_account, "-g", rg, "-o", "json"])
        or "[]"
    )
    for a in existing:
        props = a.get("properties", a)
        if props.get("principalId") == user_oid and props.get("roleDefinitionId", "").endswith(COSMOS_DATA_CONTRIBUTOR):
            log("Cosmos Data Contributor already assigned to the deploying user")
            return
    log("assigning Cosmos Data Contributor to the deploying user (for the Apply/Revert UDF)...")
    az(["cosmosdb", "sql", "role", "assignment", "create", "-a", cosmos_account, "-g", rg,
        "--role-definition-id", COSMOS_DATA_CONTRIBUTOR, "--principal-id", user_oid, "--scope", account_scope])


# --------------------------------------------------------------------------- phase 3
def _definition_parts_from_directory(
    source_dir: str,
    replacements: Optional[dict[str, str]] = None,
) -> list[dict[str, str]]:
    """Load a PBIR/TMDL item definition and hydrate deployment placeholders."""
    if not source_dir or not os.path.isdir(source_dir):
        raise FileNotFoundError(f"Fabric item source directory not found: {source_dir}")
    replacements = replacements or {}
    parts: list[dict[str, str]] = []
    unresolved: set[str] = set()
    for root, _dirs, files in os.walk(source_dir):
        for filename in sorted(files):
            full_path = os.path.join(root, filename)
            path = os.path.relpath(full_path, source_dir).replace(os.sep, "/")
            with open(full_path, "rb") as source:
                raw = source.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                payload = base64.b64encode(raw).decode("ascii")
            else:
                for placeholder, value in replacements.items():
                    text = text.replace(placeholder, value)
                unresolved.update(re.findall(r"\{\{[A-Z0-9_]+\}\}", text))
                payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
            parts.append({"path": path, "payload": payload, "payloadType": "InlineBase64"})
    if unresolved:
        raise RuntimeError(
            f"unresolved deployment placeholder(s) in {source_dir}: {', '.join(sorted(unresolved))}"
        )
    return parts


def _create_or_update_fabric_item(
    tok: Tokens,
    ws_id: str,
    item_type: str,
    display_name: str,
    parts: list[dict[str, str]],
) -> str:
    """Create or update a Fabric item from an enhanced definition."""
    hdr = tok.headers(FABRIC_SCOPE)
    collection = {"SemanticModel": "semanticModels", "Report": "reports"}[item_type]
    existing = next(
        (
            item for item in req(
                "GET", f"{FABRIC_API}/workspaces/{ws_id}/{collection}", hdr
            ).json().get("value", [])
            if item.get("displayName") == display_name
        ),
        None,
    )
    definition = {"definition": {"parts": parts}}
    if existing:
        log(f"updating existing {item_type} '{display_name}'...")
        response = req(
            "POST",
            f"{FABRIC_API}/workspaces/{ws_id}/{collection}/{existing['id']}/updateDefinition",
            hdr,
            json_body=definition,
            ok=(200, 202),
            retry_safe=True,
        )
        poll_lro(response, hdr)
        return existing["id"]

    log(f"creating {item_type} '{display_name}'...")
    response = req(
        "POST",
        f"{FABRIC_API}/workspaces/{ws_id}/{collection}",
        hdr,
        json_body={
            "displayName": display_name,
            "definition": definition["definition"],
        },
        ok=(200, 201, 202),
    )
    result = poll_lro(response, hdr) or response.json()
    return result["id"]


def deploy_powerbi_report_sources(
    tok: Tokens,
    ws_id: str,
    workspace_name: str,
    semantic_model_source: str,
    report_source: str,
    sql_endpoint: str,
    mirror_db: str,
    udf_id: str,
    display_name: str = "TravelAssistantAnalyticsReport",
) -> tuple[str, str]:
    """Deploy the source-controlled TMDL semantic model and PBIR report."""
    model_parts = _definition_parts_from_directory(
        semantic_model_source,
        {
            "{{MIRROR_SQL_ENDPOINT}}": sql_endpoint,
            "{{MIRROR_DATABASE}}": mirror_db,
        },
    )
    model_id = _create_or_update_fabric_item(
        tok, ws_id, "SemanticModel", display_name, model_parts
    )
    report_parts = _definition_parts_from_directory(
        report_source,
        {
            "{{FABRIC_WORKSPACE_NAME}}": workspace_name,
            "{{FABRIC_SEMANTIC_MODEL_ID}}": model_id,
            "{{FABRIC_WORKSPACE_ID}}": ws_id,
            "{{FABRIC_UDF_ID}}": udf_id,
        },
    )
    report_id = _create_or_update_fabric_item(
        tok, ws_id, "Report", display_name, report_parts
    )
    _bind_directquery_sso(tok, ws_id, model_id)
    _verify_dataset(
        tok,
        ws_id,
        model_id,
        "TravelAssistant OptimizationInsights",
        evidence_key="semantic_model",
    )
    _verify_dataset(
        tok,
        ws_id,
        model_id,
        "TravelAssistant OptimizationInsights",
        evidence_key="report",
        evidence_context={"report_id": report_id, "semantic_model_id": model_id},
    )
    _record_ids(semantic_model=model_id, report=report_id)
    log(f"Power BI semantic model ready: {model_id}")
    log(f"Power BI report ready: {report_id}")
    return model_id, report_id


def import_report(tok: Tokens, ws_id: str, report_path: str, sql_endpoint: str, mirror_db: str) -> bool:
    """Import a .pbix/.pbit report, point its parameters at THIS deployment's mirror, take
    ownership, bind the DirectQuery source for SSO, and verify it can query. This is a
    compatibility path; source deployment is the workshop default."""
    if not report_path or not os.path.exists(report_path):
        log(f"report artifact not found at {report_path}; skipping compatibility import")
        return False
    hdr = {"Authorization": f"Bearer {tok.get(PBI_SCOPE)}"}
    name = os.path.splitext(os.path.basename(report_path))[0]
    url = f"{PBI_API}/groups/{ws_id}/imports?datasetDisplayName={name}&nameConflict=CreateOrOverwrite"
    with open(report_path, "rb") as f:
        files = {"file": (os.path.basename(report_path), f, "application/octet-stream")}
        r = requests.post(url, headers=hdr, files=files, timeout=300)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"report import failed {r.status_code}: {r.text[:600]}")
    import_id = r.json().get("id")
    log(f"report import started: {import_id}")
    ds_id = None
    for _ in range(60):
        time.sleep(5)
        s = requests.get(f"{PBI_API}/groups/{ws_id}/imports/{import_id}", headers=hdr, timeout=60).json()
        if s.get("importState") == "Succeeded":
            ds_id = (s.get("datasets") or [{}])[0].get("id")
            break
        if s.get("importState") == "Failed":
            raise RuntimeError(f"report import failed: {json.dumps(s)[:600]}")
    if not ds_id:
        raise TimeoutError("report import did not finish")
    log(f"report imported; dataset {ds_id}")

    # Take ownership so parameter + credential calls are permitted for this principal.
    to = requests.post(
        f"{PBI_API}/groups/{ws_id}/datasets/{ds_id}/Default.TakeOver",
        headers=hdr, timeout=60,
    )
    log(f"dataset takeover: {to.status_code}")

    # Point the report at THIS deployment's mirror (the Service never prompts for these).
    if sql_endpoint:
        body = {
            "updateDetails": [
                {"name": "MirrorSQLEndpoint", "newValue": sql_endpoint},
                {"name": "MirrorDatabase", "newValue": mirror_db},
            ]
        }
        up = requests.post(
            f"{PBI_API}/groups/{ws_id}/datasets/{ds_id}/Default.UpdateParameters",
            headers={**hdr, "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        if up.status_code in (200, 202):
            log(f"parameters set: MirrorSQLEndpoint={sql_endpoint}, MirrorDatabase={mirror_db}")
        else:
            log(f"parameter update returned {up.status_code}: {up.text[:300]} "
                f"(params may not exist in this report)")
    else:
        log("no mirror SQL endpoint provided; leaving report parameters as saved")

    _bind_directquery_sso(tok, ws_id, ds_id)
    _verify_dataset(tok, ws_id, ds_id, _report_insights_entity(report_path))
    return True


def _bind_directquery_sso(tok: Tokens, ws_id: str, ds_id: str) -> None:
    """Best-effort: configure the mirror SQL DirectQuery source for Entra SSO so the report
    queries live for each viewer. Same-tenant Fabric SQL endpoints usually bind
    automatically; this is a safety net and never fails provisioning."""
    hdr = tok.headers(PBI_SCOPE)
    try:
        srcs = requests.get(
            f"{PBI_API}/groups/{ws_id}/datasets/{ds_id}/datasources",
            headers=hdr, timeout=60).json().get("value", [])
    except Exception as e:  # pragma: no cover
        log(f"datasource lookup skipped: {e}")
        return
    for d in srcs:
        gid, did = d.get("gatewayId"), d.get("datasourceId")
        if not gid or not did:
            continue
        body = {"credentialDetails": {
            "credentialType": "OAuth2",
            "useEndUserOAuth2Credentials": True,
            "encryptedConnection": "Encrypted",
            "encryptionAlgorithm": "None",
            "privacyLevel": "Organizational",
        }}
        try:
            pr = requests.patch(f"{PBI_API}/gateways/{gid}/datasources/{did}",
                                headers=hdr, json=body, timeout=60)
            log(f"DirectQuery SSO bind {did}: {pr.status_code}")
        except Exception as e:  # pragma: no cover
            log(f"DirectQuery SSO bind skipped for {did}: {e}")


def _report_insights_entity(report_path: str) -> str:
    """Read the model table backing OptimizationInsights straight from the report's PBIR
    definition, so the verify query uses the real (schema-prefixed) table name."""
    try:
        import zipfile
        z = zipfile.ZipFile(report_path)
        ents: set[str] = set()
        for n in z.namelist():
            if n.startswith("Report/definition/") and n.endswith(".json"):
                txt = z.read(n).decode("utf-8", "ignore")
                ents.update(re.findall(r'"Entity"\s*:\s*"([^"]+)"', txt))
        for e in ents:
            if e.replace(" ", "").lower().endswith("optimizationinsights"):
                return e
    except Exception:  # pragma: no cover
        pass
    return ""


def _verify_dataset(
    tok: Tokens,
    ws_id: str,
    ds_id: str,
    entity: str = "",
    *,
    evidence_key: str = "semantic_model",
    evidence_context: Optional[dict[str, str]] = None,
) -> None:
    """Run a DAX query and fail unless the imported report can read the mirror."""
    hdr = tok.headers(PBI_SCOPE)
    dax = f"EVALUATE ROW(\"rows\", COUNTROWS('{entity}'))" if entity else "EVALUATE {1}"
    q = {"queries": [{"query": dax}], "serializerSettings": {"includeNulls": True}}
    r = requests.post(f"{PBI_API}/groups/{ws_id}/datasets/{ds_id}/executeQueries",
                      headers=hdr, json=q, timeout=90)
    if r.status_code != 200:
        raise RuntimeError(
            f"report imported but dataset validation failed {r.status_code}: {r.text[:1200]}"
        )
    rows = ""
    try:
        rows = r.json()["results"][0]["tables"][0]["rows"][0]
    except Exception:  # pragma: no cover
        pass
    evidence = {
        "dataset_id": ds_id,
        "query": dax,
        "http_status": r.status_code,
        "result": rows,
    }
    evidence.update(evidence_context or {})
    EVIDENCE["query_evidence"][evidence_key] = evidence
    log("dataset query check: OK - report reads the mirror"
        + (f" ({entity}: {rows})" if entity else ""))


# --------------------------------------------------------------------------- main
def resolve_config(args: argparse.Namespace) -> dict[str, str]:
    env = load_azd_env()
    context: dict[str, str] = {}
    if not (args.subscription or env.get("AZURE_SUBSCRIPTION_ID")) or not (
        args.tenant or env.get("AZURE_TENANT_ID")
    ):
        context = azure_context()
    endpoint = args.cosmos_endpoint or env.get("COSMOSDB_ENDPOINT", "")
    account = args.cosmos_account
    if not account and endpoint:
        account = endpoint.replace("https://", "").split(".")[0]
    cfg = {
        "rg": args.resource_group or env.get("RG_NAME", ""),
        "sub": args.subscription or env.get("AZURE_SUBSCRIPTION_ID", "") or context.get("subscription", ""),
        "tenant_id": args.tenant or env.get("AZURE_TENANT_ID", "") or context.get("tenant", ""),
        "capacity_name": args.capacity or env.get("FABRIC_CAPACITY_NAME", ""),
        "workspace_name": args.workspace,
        "cosmos_account": account or "",
        "cosmos_endpoint": endpoint,
        "db_name": args.database or env.get("COSMOS_DB_DATABASE_NAME", "TravelAssistant"),
        "app_identity_oid": args.app_identity_principal_id or env.get("MANAGED_IDENTITY_PRINCIPAL_ID", ""),
    }
    return cfg


def main() -> int:
    global ACTIVE_ARGS
    p = argparse.ArgumentParser(description="Provision Fabric analytics for Travel Assistant optimization")
    p.add_argument(
        "--environment",
        choices=["development", "staging"],
        default="development",
        help="deployment contract; staging requires source deployment and blocking verification",
    )
    p.add_argument(
        "--verify-semantic-model",
        action="store_true",
        help="require a successful semantic-model query before staging is Verified",
    )
    p.add_argument(
        "--verify-report",
        action="store_true",
        help="require source-controlled report binding/query evidence before staging is Verified",
    )
    p.add_argument(
        "--evidence-output",
        default=str(ROOT / ".local" / "fabric-provision-staging-evidence.json"),
        help="machine-readable provisioning evidence JSON",
    )
    p.add_argument(
        "--no-cloud",
        action="store_true",
        help="perform source/evidence preflight only and exit Unverified without cloud calls",
    )
    p.add_argument("--workspace", default="Multi-Agent Travel Workshop", help="new workspace display name")
    p.add_argument("--capacity", help="Fabric capacity display name (default from azd FABRIC_CAPACITY_NAME)")
    p.add_argument("--resource-group", help="Cosmos resource group (default azd RG_NAME)")
    p.add_argument("--subscription")
    p.add_argument("--tenant")
    p.add_argument("--cosmos-account", help="Cosmos account name (default derived from COSMOSDB_ENDPOINT)")
    p.add_argument("--cosmos-endpoint")
    p.add_argument("--app-identity-principal-id",
                   help="app managed identity object id to also grant the mirroring role "
                        "(default from azd MANAGED_IDENTITY_PRINCIPAL_ID)")
    p.add_argument("--database", help="Cosmos database name (default TravelAssistant)")
    p.add_argument("--connection-id", help="pre-created OAuth2 Cosmos connection id (skips the interactive prompt)")
    p.add_argument("--notebook", default=os.path.join(os.path.dirname(__file__), "ConversionFunnelReverseETL.ipynb"),
                   help="notebook to upload (default: the Module 09 learner notebook with TODOs)")
    p.add_argument("--solution", action="store_true",
                   help="upload the completed *_solution notebook instead of the learner TODO version "
                        "(use for 02_completed / the demo)")
    powerbi_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "powerbi")
    p.add_argument("--report",
                   help="optional .pbix/.pbit compatibility override; by default deploys "
                        "the source-controlled PBIR/TMDL definitions")
    p.add_argument("--pbit", help="(deprecated) alias for --report")
    p.add_argument("--report-source",
                   default=os.path.join(powerbi_dir, "TravelAssistantAnalyticsReport.Report"),
                   help="PBIR report definition directory")
    p.add_argument("--semantic-model-source",
                   default=os.path.join(powerbi_dir, "TravelAssistantAnalyticsReport.SemanticModel"),
                   help="TMDL semantic-model definition directory")
    p.add_argument("--phase", choices=["1", "2", "3", "report", "all"], default="all",
                   help="1=workspace+identity+rbac, 2=reuse workspace+update mirror/notebook/udf, 3=all+report "
                        "deployment, report=ONLY deploy the report (reuses the persisted "
                        "FABRIC_WORKSPACE_ID/FABRIC_MIRROR_ID)")
    args = p.parse_args()
    ACTIVE_ARGS = args
    if args.solution:
        base, ext = os.path.splitext(args.notebook)
        if not base.endswith("_solution"):
            args.notebook = f"{base}_solution{ext}"
    _initialize_evidence(args)

    if args.environment == "staging":
        if args.phase != "all":
            _write_evidence(args, "Unverified", "staging requires --phase all")
            return 2
        if not (args.verify_semantic_model and args.verify_report):
            _write_evidence(
                args,
                "Unverified",
                "staging requires --verify-semantic-model and --verify-report",
            )
            return 2
        if args.report or args.pbit:
            _write_evidence(
                args,
                "Unverified",
                "staging requires source-controlled PBIR/TMDL deployment, not PBIX/PBIT import",
            )
            return 2
        if args.no_cloud:
            _write_evidence(
                args,
                "Unverified",
                "cloud execution intentionally disabled; staging remains blocking",
            )
            return 2
        if not args.connection_id:
            _write_evidence(
                args,
                "Unverified",
                "staging requires an explicit Cosmos connection id",
            )
            return 2

    cfg = resolve_config(args)
    required = ["rg", "sub", "cosmos_account"]
    if args.phase in {"1", "3", "all"}:
        required.append("capacity_name")
    missing = [key for key in required if not cfg.get(key)]
    if missing:
        if args.environment == "staging":
            _write_evidence(
                args,
                "Unverified",
                f"missing staging configuration: {', '.join(missing)}",
            )
            return 2
        die(f"missing config: {missing} (set via azd env or CLI flags)")
    log(f"config: {json.dumps({k: v for k, v in cfg.items()}, indent=0)}")

    tok = Tokens()
    if args.environment == "staging":
        try:
            for scope in (FABRIC_SCOPE, PBI_SCOPE, ARM_SCOPE):
                tok.get(scope)
        except Exception as exc:
            _write_evidence(
                args,
                "Unverified",
                f"cloud credentials unavailable: {type(exc).__name__}: {exc}",
            )
            return 2

    # ---- report-only phase (reuses the workspace/mirror from a prior phase-1/2 run) ----
    if args.phase == "report":
        env = load_azd_env()
        ws_id = env.get("FABRIC_WORKSPACE_ID", "")
        mirror_id = env.get("FABRIC_MIRROR_ID", "")
        if not ws_id or not mirror_id:
            die("phase 'report' needs FABRIC_WORKSPACE_ID and FABRIC_MIRROR_ID in the azd "
                "env (run phases 1-2 first)")
        sql_ep = get_mirror_sql_endpoint(tok, ws_id, mirror_id)
        report_path = args.pbit or args.report
        if report_path:
            imported = import_report(
                tok, ws_id, report_path, sql_ep, f"{cfg['db_name']}Analytics"
            )
            if not imported:
                die("report phase did not import an artifact")
            log("REPORT IMPORT AND VALIDATION COMPLETE.")
            print(json.dumps({
                "workspaceId": ws_id, "report": os.path.basename(report_path)
            }, indent=2))
            return 0

        udf_id = env.get("FABRIC_UDF_ID", "")
        if not udf_id:
            udf_items = req(
                "GET", f"{FABRIC_API}/workspaces/{ws_id}/userDataFunctions",
                tok.headers(FABRIC_SCOPE)
            ).json().get("value", [])
            udf_id = next(
                (
                    item["id"] for item in udf_items
                    if item.get("displayName") == "optimization-apply-loop"
                ),
                "",
            )
        if not udf_id:
            die("report deployment needs FABRIC_UDF_ID (run phase 2 first)")
        model_id, report_id = deploy_powerbi_report_sources(
            tok=tok,
            ws_id=ws_id,
            workspace_name=cfg["workspace_name"],
            semantic_model_source=args.semantic_model_source,
            report_source=args.report_source,
            sql_endpoint=sql_ep,
            mirror_db=f"{cfg['db_name']}Analytics",
            udf_id=udf_id,
        )
        persist_env({
            "FABRIC_SEMANTIC_MODEL_ID": model_id,
            "FABRIC_REPORT_ID": report_id,
        })
        log("REPORT SOURCE DEPLOYMENT AND VALIDATION COMPLETE.")
        print(json.dumps({
            "workspaceId": ws_id,
            "semanticModelId": model_id,
            "reportId": report_id,
        }, indent=2))
        return

    # ---- Phase 1 (fully automated) or existing-topology reuse ----
    if args.phase == "2":
        existing = load_azd_env()
        ws_id = existing.get("FABRIC_WORKSPACE_ID", "")
        if not ws_id:
            die("phase 2 reuses existing topology and requires FABRIC_WORKSPACE_ID")
        capacity_id = existing.get("FABRIC_CAPACITY_ID", "")
        sp = None
        log(f"PHASE 1 SKIPPED. reusing workspace={ws_id}")
    else:
        capacity_id = wait_for_capacity(tok, cfg["capacity_name"])
        ws_id = get_or_create_workspace(tok, cfg["workspace_name"], capacity_id)
        _record_ids(workspace=ws_id)
        persist_env({"FABRIC_WORKSPACE_ID": ws_id, "FABRIC_CAPACITY_NAME": cfg["capacity_name"]})
        sp = provision_workspace_identity(tok, ws_id)
        grant_cosmos_rbac(cfg["cosmos_account"], cfg["rg"], cfg["sub"], sp or "", cfg.get("app_identity_oid", ""))
        enable_cosmos_bypass(cfg["cosmos_account"], cfg["rg"], cfg["tenant_id"], ws_id)
        log(f"PHASE 1 COMPLETE. workspace={ws_id}")

    if args.phase == "1":
        print(json.dumps({"workspaceId": ws_id, "capacityId": capacity_id, "workspaceIdentitySp": sp}, indent=2))
        return 0

    # ---- Phase 2 (needs the manual OAuth2 connection) ----
    connection_id = args.connection_id
    if not connection_id:
        print("\n" + "=" * 78)
        print("MANUAL STEP - create the Cosmos connection (one time):")
        print("  1. Fabric portal -> Settings (gear) -> Manage connections and gateways -> Connections -> + New.")
        print("  2. Connection type: Azure Cosmos DB v2 -> OAuth 2.0 (Organizational account) -> sign in -> Create.")
        print(f"     Account URL: {cfg['cosmos_endpoint']}")
        print(f"     (Can't copy it? Azure portal -> Cosmos account '{cfg['cosmos_account']}' in "
              f"resource group '{cfg['rg']}' -> Overview -> copy the URI.)")
        print("  3. Open the connection -> Settings -> copy its Connection ID (a GUID).")
        print("=" * 78)
        connection_id = input("Paste the Cosmos connection id (or blank to stop after phase 1): ").strip()
        if not connection_id:
            log("no connection id provided; stopping after phase 1.")
            return 0

    mirror_id = get_or_create_mirror(tok, ws_id, connection_id, cfg["db_name"])
    _record_ids(workspace=ws_id, mirror=mirror_id)
    persist_env({"FABRIC_MIRROR_ID": mirror_id})

    # Pre-fill the Module 09 notebook's parameters (Cosmos + the mirror SQL endpoint);
    # pricing comes from the mirrored Configuration table, so no pricing param.
    sql_ep = get_mirror_sql_endpoint(tok, ws_id, mirror_id)
    nb_params = {
        "COSMOS_ENDPOINT": cfg["cosmos_endpoint"],
        "COSMOS_DATABASE": cfg["db_name"],
        "INSIGHTS_CONTAINER": "OptimizationInsights",
        "TENANT_ID": cfg.get("tenant_id", ""),
        "SOURCE_SCHEMA": cfg["db_name"],
        "SQL_EP": sql_ep,
        "SQL_DB": f"{cfg['db_name']}Analytics",
    }
    notebook_id = upload_notebook(tok, ws_id, args.notebook, nb_params)
    if not notebook_id:
        die("Phase 2 requires the reverse-ETL notebook before creating its controller pipeline")
    pipeline_id = provision_demo_tenant_pipeline(tok, ws_id, notebook_id)
    _record_ids(notebook=notebook_id, pipeline=pipeline_id)
    persist_env({
        "FABRIC_NOTEBOOK_ID": notebook_id,
        "FABRIC_DEMO_TENANTS_PIPELINE_ID": pipeline_id,
    })

    # Deploy the translytical Apply/Revert User Data Function (and grant the deploying
    # user Cosmos data-plane write) so Power BI buttons work with no manual portal steps.
    udf_src = os.path.join(os.path.dirname(__file__), "udf", "optimization_policy_functions.py")
    udf_id = deploy_udf(tok, ws_id, udf_src, cfg["cosmos_endpoint"], cfg["db_name"])
    if udf_id:
        _record_ids(udf=udf_id)
        persist_env({"FABRIC_UDF_ID": udf_id})
        grant_cosmos_data_contributor(cfg["cosmos_account"], cfg["rg"], cfg["sub"])
    log(f"PHASE 2 COMPLETE. mirror={mirror_id} pipeline={pipeline_id}")

    if args.phase == "2":
        print(json.dumps({
            "workspaceId": ws_id,
            "mirrorId": mirror_id,
            "notebookId": notebook_id,
            "demoTenantsPipelineId": pipeline_id,
            "udfId": udf_id,
        }, indent=2))
        return 0

    # ---- Phase 3 (deploy the source-controlled Power BI report/model) ----
    report_path = args.pbit or args.report
    if report_path:
        imported = import_report(
            tok, ws_id, report_path, sql_ep, f"{cfg['db_name']}Analytics"
        )
        if not imported:
            die("report phase did not import an artifact")
    elif not udf_id:
        die("report source deployment requires the Phase 2 UDF")
    else:
        model_id, report_id = deploy_powerbi_report_sources(
            tok=tok,
            ws_id=ws_id,
            workspace_name=cfg["workspace_name"],
            semantic_model_source=args.semantic_model_source,
            report_source=args.report_source,
            sql_endpoint=sql_ep,
            mirror_db=f"{cfg['db_name']}Analytics",
            udf_id=udf_id,
        )
        persist_env({
            "FABRIC_SEMANTIC_MODEL_ID": model_id,
            "FABRIC_REPORT_ID": report_id,
        })
    log("ALL PHASES COMPLETE.")
    print(json.dumps({"workspaceId": ws_id, "mirrorId": mirror_id}, indent=2))
    _record_ids(workspace=ws_id, mirror=mirror_id, notebook=notebook_id, pipeline=pipeline_id, udf=udf_id)
    if args.environment == "staging":
        missing_ids = [key for key, value in EVIDENCE["ids"].items() if not value]
        if missing_ids:
            _write_evidence(
                args,
                "Failed",
                f"deployment completed without required ids: {', '.join(missing_ids)}",
            )
            return 1
        if not all(EVIDENCE["query_evidence"].values()):
            _write_evidence(
                args,
                "Failed",
                "semantic-model/report query evidence is incomplete",
            )
            return 1
        _write_evidence(args, "Verified")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if (
            ACTIVE_ARGS is not None
            and ACTIVE_ARGS.environment == "staging"
            and EVIDENCE
            and EVIDENCE.get("completed_utc") is None
            and int(exc.code or 0) != 0
        ):
            _write_evidence(
                ACTIVE_ARGS,
                "Unverified",
                "provisioning exited before verified completion; inspect preceding error",
            )
        raise
    except Exception as exc:
        if ACTIVE_ARGS is not None and ACTIVE_ARGS.environment == "staging" and EVIDENCE:
            text = f"{type(exc).__name__}: {exc}"
            unverified_terms = (
                "credential",
                "capacity",
                "connection",
                "workspace",
                "not found",
                "missing",
                "unavailable",
                "timed out",
            )
            status = "Unverified" if any(term in text.lower() for term in unverified_terms) else "Failed"
            _write_evidence(ACTIVE_ARGS, status, text)
        raise
