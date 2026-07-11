#!/usr/bin/env python3
"""EXPERIMENTAL / PARKED — automated Cosmos DB OAuth2 connection creation for Fabric.

⚠️  This is NOT wired into the shipped provisioning flow. The workshop ships with the
    **manual** portal connection step (see analytics/fabric/README.md). This script is
    kept so we can re-validate and turn it on the moment the Fabric gateway team ships the
    missing pieces. See analytics/docs/parking-lot.md ("Fabric auto DMTS connection").

What works (validated 2026-07-11 on the MSIT tenant):
  - Creating the Cosmos OAuth2 connection programmatically via the DMTS gateway datasource
    endpoint returns 200 and yields a connection/datasource id.
  - The connection's embedded access token must be minted with the **Cosmos DB audience**
    (`az account get-access-token --resource https://cosmos.azure.com` -> aud
    a232010e-820c-4083-83bb-3ace5fc29d0b). Using a Fabric-audience token is what made the
    mirror fail for whoever tried this before us — the portal UX sets the Cosmos audience
    because it knows the target is Cosmos DB.
  - With the correct data-plane RBAC (readMetadata + readAnalytics on the connection
    identity — see provision_fabric.py), a mirror can use this connection.

What is still broken (why this is PARKED):
  1. **No refresh token.** `az account get-access-token` returns only an access token
     (the connection's RefreshToken is empty), so the connection dies when that token
     expires (~60-90 min). A durable connection needs an auth-code flow that yields a
     refresh token the **Fabric gateway OAuth app** can redeem (`useCustomOAuthApp:false`).
     The Fabric gateway team is investigating setting the target audience + refresh on the
     automated path (expected ~Sept). Until then this is demo-only.
  2. **MSIT-only endpoint.** The DMTS gateway cluster endpoint below is the MSIT redirect
     (`df-msit-scus-redirect...`). Production uses a different endpoint; discover it from
     the Power BI global service (TODO) rather than hardcoding.

Usage (once unblocked):
    python create_oauth_connection.py \
        --host https://<account>.documents.azure.com:443/ \
        [--endpoint https://df-msit-scus-redirect.analysis.windows.net] \
        [--name cdb-mirror-oauth-conn]

Prints the created connection id, which you can pass to
`provision_fabric.py --phase 2 --connection-id <id>`.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys

import requests

# MSIT gateway cluster redirect endpoint. Production differs — discover it from the
# Power BI global service instead of hardcoding once this path is productionized.
DEFAULT_ENDPOINT = "https://df-msit-scus-redirect.analysis.windows.net"

# The Cosmos DB audience: az .../resource=https://cosmos.azure.com mints aud=a232010e-...
COSMOS_RESOURCE = "https://cosmos.azure.com"
PBI_RESOURCE = "https://analysis.windows.net/powerbi/api"


def az_token(resource: str) -> dict:
    exe = "az.cmd" if sys.platform.startswith("win") else "az"
    out = subprocess.run(
        [exe, "account", "get-access-token", "--resource", resource],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"az get-access-token failed for {resource}: {out.stderr[:300]}")
    return json.loads(out.stdout)


def build_body(host: str, name: str, cosmos_access_token: str, expires: str) -> dict:
    return {
        "datasourceName": name,
        "datasourceType": "Extension",
        "connectionDetails": json.dumps({"host": host}),
        "singleSignOnType": "None",
        "skipTestConnectionOnce": True,
        "mashupTestConnectionDetails": {
            "functionName": "CosmosDB.Contents",
            "moduleName": "CosmosDB",
            "moduleVersion": "1.0.4",
            "parameters": [
                {"name": "host", "type": "text", "isRequired": True, "value": host},
                {"name": "options", "type": "nullable record", "isRequired": False,
                 "recordParameters": [
                     {"name": "NUMBER_OF_RETRIES", "type": "nullable text", "isRequired": False},
                     {"name": "ENABLE_AVERAGE_FUNCTION_PASSDOWN", "type": "nullable text", "isRequired": False},
                     {"name": "ENABLE_SORT_PASSDOWN_FOR_MULTIPLE_COLUMNS", "type": "nullable text", "isRequired": False},
                 ]},
            ],
        },
        "referenceDatasource": False,
        "credentialDetails": {
            "credentialType": "OAuth2",
            # NOTE: RefreshToken is empty — this is the unsolved durability gap (see module docstring).
            "credentials": json.dumps({"credentialData": [
                {"name": "AccessToken", "value": cosmos_access_token},
                {"name": "Expires", "value": expires},
                {"name": "RefreshToken", "value": ""},
            ]}),
            "encryptedConnection": "Any",
            "privacyLevel": "Organizational",
            "skipTestConnectionOnce": True,
            "encryptionAlgorithm": "NONE",
            "credentialSources": [],
        },
        "allowDatasourceThroughGateway": False,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", required=True, help="Cosmos endpoint, e.g. https://acct.documents.azure.com:443/")
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="DMTS gateway cluster endpoint (MSIT by default)")
    p.add_argument("--name", default="cdb-mirror-oauth-conn")
    args = p.parse_args()

    print("[parked] This automated connection is DEMO-ONLY (no refresh token). See module docstring.")
    pbi = az_token(PBI_RESOURCE)
    cos = az_token(COSMOS_RESOURCE)
    exp_raw = str(cos.get("expiresOn") or cos.get("expires_on") or "")
    try:
        dt = datetime.datetime.strptime(exp_raw.split(".")[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        dt = datetime.datetime.now() + datetime.timedelta(hours=1)
    expires = dt.strftime("%m/%d/%Y %I:%M:%S %p")

    url = f"{args.endpoint.rstrip('/')}/v2.0/myorg/me/gatewayClusterCloudDatasource"
    body = build_body(args.host, args.name, cos["accessToken"], expires)
    r = requests.post(url, headers={"Authorization": f"Bearer {pbi['accessToken']}",
                                    "Content-Type": "application/json"}, json=body, timeout=60)
    if r.status_code not in (200, 201):
        raise SystemExit(f"create failed {r.status_code}: {r.text[:800]}")
    conn_id = r.json().get("id")
    print(f"connection created: {conn_id}")
    print("Reminder: this token expires soon and cannot refresh — for demo use only.")


if __name__ == "__main__":
    main()
