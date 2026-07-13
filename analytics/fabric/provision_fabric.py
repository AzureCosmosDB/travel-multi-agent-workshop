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
    - create the mirrored database (OptimizationTurns / Trips / OptimizationPolicies /
      Configuration) + start
    - create the Direct Lake semantic model over the mirror
    - upload the parameterized reverse-ETL notebook (endpoints only; pricing comes from
      the mirrored Configuration table) + schedule it

  Phase 3 (optional):
    - import a .pbit and set its MirrorSQLEndpoint / MirrorDatabase parameters

Auth uses your `az login` (DefaultAzureCredential). Config is read from `azd env get-values`
by default; override with CLI flags. Idempotent: existing workspace/mirror/etc. are reused.

See analytics/fabric/README.md for the proven REST payloads this automates.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from typing import Any, Optional

import requests

try:
    from azure.identity import DefaultAzureCredential
except ImportError:  # pragma: no cover
    print("azure-identity is required: pip install azure-identity", file=sys.stderr)
    raise

FABRIC_API = "https://api.fabric.microsoft.com/v1"
PBI_API = "https://api.powerbi.com/v1.0/myorg"
ARM_API = "https://management.azure.com"

FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
PBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
ARM_SCOPE = "https://management.azure.com/.default"

# Cosmos built-in Data Contributor data-plane role definition id (fixed GUID).
COSMOS_DATA_CONTRIBUTOR = "00000000-0000-0000-0000-000000000002"

# Tables to mirror (schema name == Cosmos DB name; set at runtime).
MIRROR_TABLES = ["OptimizationTurns", "Trips", "OptimizationPolicies", "Configuration", "Messages", "OptimizationInsights"]


# --------------------------------------------------------------------------- creds
class Tokens:
    """Lazily-cached AAD tokens for the three APIs we call."""

    def __init__(self) -> None:
        self._cred = DefaultAzureCredential(exclude_interactive_browser_credential=False)
        self._cache: dict[str, tuple[str, float]] = {}

    def get(self, scope: str) -> str:
        tok, exp = self._cache.get(scope, (None, 0.0))
        if tok and time.time() < exp - 120:
            return tok
        t = self._cred.get_token(scope)
        self._cache[scope] = (t.token, t.expires_on)
        return t.token

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


def req(method: str, url: str, headers: dict, *, json_body: Any = None, ok=(200, 201, 202)) -> requests.Response:
    r = requests.request(method, url, headers=headers, json=json_body, timeout=120)
    if r.status_code not in ok:
        raise RuntimeError(f"{method} {url} -> {r.status_code}: {r.text[:600]}")
    return r


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
        s = requests.get(loc, headers=headers, timeout=60)
        status = s.json().get("status") if s.text else None
        if status in ("Succeeded", "Completed"):
            result_url = s.headers.get("Location")
            if result_url:
                rr = requests.get(result_url, headers=headers, timeout=60)
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
    die(f"capacity '{capacity_name}' did not become Active within {timeout}s")
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
        c = req(
            "POST",
            f"{FABRIC_API}/workspaces",
            tok.headers(FABRIC_SCOPE),
            json_body={"displayName": name, "description": "Travel Assistant optimization analytics"},
        )
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
               hdr, json_body={}, ok=(200, 202))
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
            hdr, json_body={"definition": {"parts": parts}}, ok=(200, 202))
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
    name = "TravelAssistantOptimizationInsights"
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
        )
        return existing["id"]
    log("creating notebook...")
    resp = req("POST", f"{FABRIC_API}/workspaces/{ws_id}/notebooks", hdr, json_body=body, ok=(200, 201, 202))
    result = poll_lro(resp, hdr) or resp.json()
    return result.get("id")


# --------------------------------------------------------------------------- phase 3
def import_pbit(tok: Tokens, ws_id: str, pbit_path: str, sql_endpoint: str, mirror_db: str) -> None:
    if not os.path.exists(pbit_path):
        log(f".pbit not found at {pbit_path}; skipping import (build it from the guide first)")
        return
    hdr = {"Authorization": f"Bearer {tok.get(PBI_SCOPE)}"}
    name = os.path.splitext(os.path.basename(pbit_path))[0]
    url = f"{PBI_API}/groups/{ws_id}/imports?datasetDisplayName={name}&nameConflict=CreateOrOverwrite"
    with open(pbit_path, "rb") as f:
        files = {"file": (os.path.basename(pbit_path), f, "application/octet-stream")}
        r = requests.post(url, headers=hdr, files=files, timeout=300)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"pbit import failed {r.status_code}: {r.text[:600]}")
    import_id = r.json().get("id")
    log(f".pbit import started: {import_id}")
    ds_id = None
    for _ in range(60):
        time.sleep(5)
        s = requests.get(f"{PBI_API}/groups/{ws_id}/imports/{import_id}", headers=hdr, timeout=60).json()
        if s.get("importState") == "Succeeded":
            ds_id = (s.get("datasets") or [{}])[0].get("id")
            break
        if s.get("importState") == "Failed":
            raise RuntimeError(f"pbit import failed: {json.dumps(s)[:600]}")
    if not ds_id:
        raise TimeoutError("pbit import did not finish")
    log(f".pbit imported; dataset {ds_id}. Updating parameters...")
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
    if up.status_code not in (200, 202):
        log(f"parameter update returned {up.status_code}: {up.text[:300]} (params may not exist in this .pbit)")
    else:
        log("dataset parameters updated (MirrorSQLEndpoint / MirrorDatabase)")


# --------------------------------------------------------------------------- main
def resolve_config(args: argparse.Namespace) -> dict[str, str]:
    env = load_azd_env()
    endpoint = args.cosmos_endpoint or env.get("COSMOSDB_ENDPOINT", "")
    account = args.cosmos_account
    if not account and endpoint:
        account = endpoint.replace("https://", "").split(".")[0]
    cfg = {
        "rg": args.resource_group or env.get("RG_NAME", ""),
        "sub": args.subscription or env.get("AZURE_SUBSCRIPTION_ID", "") or (az(["account", "show", "--query", "id", "-o", "tsv"]) if not args.subscription else args.subscription),
        "tenant_id": args.tenant or env.get("AZURE_TENANT_ID", "") or az(["account", "show", "--query", "tenantId", "-o", "tsv"]),
        "capacity_name": args.capacity or env.get("FABRIC_CAPACITY_NAME", ""),
        "workspace_name": args.workspace,
        "cosmos_account": account or "",
        "cosmos_endpoint": endpoint,
        "db_name": args.database or env.get("COSMOS_DB_DATABASE_NAME", "TravelAssistant"),
        "app_identity_oid": args.app_identity_principal_id or env.get("MANAGED_IDENTITY_PRINCIPAL_ID", ""),
    }
    return cfg


def main() -> None:
    p = argparse.ArgumentParser(description="Provision Fabric analytics for Travel Assistant optimization")
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
    p.add_argument("--notebook", default=os.path.join(os.path.dirname(__file__), "TravelAssistantOptimizationInsights.ipynb"))
    p.add_argument("--pbit", help="path to a .pbit to import (optional)")
    p.add_argument("--phase", choices=["1", "2", "3", "all"], default="all",
                   help="1=workspace+identity+rbac, 2=+mirror+notebook, 3=+pbit import")
    args = p.parse_args()

    cfg = resolve_config(args)
    missing = [k for k in ("rg", "sub", "capacity_name", "cosmos_account") if not cfg.get(k)]
    if missing:
        die(f"missing config: {missing} (set via azd env or CLI flags)")
    log(f"config: {json.dumps({k: v for k, v in cfg.items()}, indent=0)}")

    tok = Tokens()

    # ---- Phase 1 (fully automated) ----
    capacity_id = wait_for_capacity(tok, cfg["capacity_name"])
    ws_id = get_or_create_workspace(tok, cfg["workspace_name"], capacity_id)
    persist_env({"FABRIC_WORKSPACE_ID": ws_id, "FABRIC_CAPACITY_NAME": cfg["capacity_name"]})
    sp = provision_workspace_identity(tok, ws_id)
    grant_cosmos_rbac(cfg["cosmos_account"], cfg["rg"], cfg["sub"], sp or "", cfg.get("app_identity_oid", ""))
    enable_cosmos_bypass(cfg["cosmos_account"], cfg["rg"], cfg["tenant_id"], ws_id)
    log(f"PHASE 1 COMPLETE. workspace={ws_id}")

    if args.phase == "1":
        print(json.dumps({"workspaceId": ws_id, "capacityId": capacity_id, "workspaceIdentitySp": sp}, indent=2))
        return

    # ---- Phase 2 (needs the manual OAuth2 connection) ----
    connection_id = args.connection_id
    if not connection_id:
        print("\n" + "=" * 78)
        print("MANUAL STEP — create the Cosmos connection (one time):")
        print(f"  1. Open the workspace in the Fabric portal (id {ws_id}).")
        print("  2. New -> Mirrored Azure Cosmos DB -> sign in with your Organizational")
        print(f"     account (OAuth2). Host: {cfg['cosmos_endpoint']}")
        print("  3. Once the connection exists, copy its connection id.")
        print("=" * 78)
        connection_id = input("Paste the Cosmos connection id (or blank to stop after phase 1): ").strip()
        if not connection_id:
            log("no connection id provided; stopping after phase 1.")
            return

    mirror_id = get_or_create_mirror(tok, ws_id, connection_id, cfg["db_name"])
    persist_env({"FABRIC_MIRROR_ID": mirror_id})

    # Model pricing is read by the notebook from the mirrored Configuration table
    # (type='model_pricing'), seeded by azd — no pricing param needed here.
    nb_params = {
        "COSMOS_ENDPOINT": cfg["cosmos_endpoint"],
        "SOURCE_SCHEMA": cfg["db_name"],
    }
    upload_notebook(tok, ws_id, args.notebook, nb_params)
    log(f"PHASE 2 COMPLETE. mirror={mirror_id}")

    if args.phase == "2":
        print(json.dumps({"workspaceId": ws_id, "mirrorId": mirror_id}, indent=2))
        return

    # ---- Phase 3 (optional .pbit import) ----
    if args.pbit:
        # SQL endpoint of the mirror is discoverable once mirroring is running.
        sql_endpoint = ""  # left blank -> user can pass a fully-parameterized pbit
        import_pbit(tok, ws_id, args.pbit, sql_endpoint, f"{cfg['db_name']}Analytics")
    log("ALL PHASES COMPLETE.")
    print(json.dumps({"workspaceId": ws_id, "mirrorId": mirror_id}, indent=2))


if __name__ == "__main__":
    main()
