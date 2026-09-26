"""Controlled Demo 4 deployment verifier.

Live modes are intentionally explicit and fail closed.  This command never performs Apply,
traffic generation, or timestamp freshening.  ``post-traffic`` observes already-generated data
and can optionally run exactly one recompute path.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import http.client
import json
import logging
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

_PYTHON_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _PYTHON_ROOT.parents[1]
sys.path.insert(0, str(_PYTHON_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_PYTHON_ROOT / ".env", override=False)

for logger_name in ("azure", "azure.core.pipeline.policies.http_logging_policy"):
    logging.getLogger(logger_name).setLevel(logging.WARNING)

from src.app.services.controlled_demo4 import (  # noqa: E402
    BURST_ANCHOR,
    BURST_VERSION,
    COHORT_CONTAINERS,
    DEFAULT_ANCHOR,
    DERIVED_CONTAINERS,
    EXPECTED_FUNNEL,
    FIXTURE_VERSION,
    TENANTS,
    TURN_COUNT,
    WINDOW_MINUTES,
    build_tenant_manifest,
    controlled_fixture_session_prefix,
    evaluate_controlled_demo4,
    is_controlled_fixture_row,
)
from src.app.services.controlled_demo4_verifier import (  # noqa: E402
    AzureCliTokenProvider,
    AzurePowerShellTokenCredential,
    AzurePowerShellTokenProvider,
    ChainedTokenProvider,
    ControlledDemo4Verifier,
    CosmosBackupStore,
    DEPLOYMENT_TRANSPORTS,
    DefaultCredentialTokenProvider,
    IdentityIntent,
    IdentityPreflight,
    MIRROR_TABLES,
    MODES,
    RECOMPUTE_CHOICES,
    VerificationError,
    VerifierConfig,
    poll_mirror_convergence,
    sha256_json,
    validate_backup_manifest,
    verify_hosted_session,
    write_durable_json,
)


def _resolved_command(command: list[str], *, operation: str, cwd: Path) -> list[str]:
    executable = shutil.which(command[0])
    if executable is None:
        raise VerificationError(
            f"{operation}: executable not found: {command[0]!r}; cwd={cwd}"
        )
    return [executable, *command[1:]]


def _run_command(
    command: list[str],
    *,
    operation: str,
    cwd: Path,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    resolved = _resolved_command(command, operation=operation, cwd=cwd)
    try:
        return subprocess.run(resolved, cwd=cwd, **kwargs)
    except FileNotFoundError as exc:
        raise VerificationError(
            f"{operation}: file or executable not found while running "
            f"{resolved[0]!r}; cwd={cwd}; path={exc.filename or '<unknown>'}"
        ) from exc


def _run_json(command: list[str], *, cwd: Path = _REPO_ROOT) -> Any:
    completed = _run_command(
        command,
        operation=f"JSON command {' '.join(command)}",
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise VerificationError(
            f"command failed ({completed.returncode}): {' '.join(command)}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise VerificationError(
            f"command did not emit JSON: {' '.join(command)}"
        ) from exc


def _azd_values() -> dict[str, str]:
    completed = _run_command(
        ["azd", "env", "get-values"],
        operation="read azd environment values",
        cwd=_PYTHON_ROOT.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise VerificationError(completed.stderr.strip() or "azd env get-values failed")
    values: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
    return values


def select_deployment_transport(
    requested: str,
    *,
    azd_authenticated: bool,
    cli_tenant: str = "",
    cli_subscription: str = "",
    intended_tenant: str,
    intended_subscription: str,
) -> str:
    if requested == "direct":
        return "direct"
    matches = (
        azd_authenticated
        and cli_tenant.lower() == intended_tenant.lower()
        and cli_subscription.lower() == intended_subscription.lower()
    )
    if requested == "azd":
        if not matches:
            raise VerificationError(
                "azd transport requested but azd/Azure CLI authentication does not match "
                "the intended tenant and subscription"
            )
        return "azd"
    return "azd" if matches else "direct"


def container_image_with_tag(image: str, tag: str) -> str:
    repository = image.split("@", 1)[0]
    last_slash = repository.rfind("/")
    colon = repository.rfind(":")
    if colon > last_slash:
        repository = repository[:colon]
    return f"{repository}:{tag}"


def update_template_image(
    template: dict[str, Any], current_image: str, replacement_image: str
) -> dict[str, Any]:
    updated = copy.deepcopy(template)
    matches = [
        container
        for container in updated.get("containers", [])
        if container.get("image") == current_image
    ]
    if len(matches) != 1:
        raise VerificationError(
            f"expected exactly one Container App image field matching {current_image}, "
            f"found {len(matches)}"
        )
    matches[0]["image"] = replacement_image
    return updated


def _all_rows(container: Any, tenant: str | None = None) -> list[dict[str, Any]]:
    if tenant is None:
        query = "SELECT * FROM c"
        parameters: list[dict[str, Any]] = []
    else:
        query = "SELECT * FROM c WHERE c.tenantId = @tenant"
        parameters = [{"name": "@tenant", "value": tenant}]
    return list(
        container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
        )
    )


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if any(marker in key.lower() for marker in ("token", "secret", "credential", "password", "api_key"))
                else _redact_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


_HTTP_MAX_ATTEMPTS = 4
_HTTP_BACKOFF_SECONDS = 0.5
_HTTP_BACKOFF_CAP_SECONDS = 8.0
_TRANSIENT_HTTP_STATUS = {408, 429, *range(500, 600)}


def _safe_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query_names = sorted(
        {
            key
            for key, _ in urllib.parse.parse_qsl(
                parsed.query, keep_blank_values=True
            )
        }
    )
    safe_query = "&".join(f"{key}=<redacted>" for key in query_names)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, safe_query, "")
    )


_DEFAULT_PIP_INDEX_URL = "https://pypi.org/simple"
_DEFAULT_NPM_REGISTRY_URL = "https://registry.npmjs.org/"


def validate_pip_index_url(value: str) -> str:
    candidate = value.strip()
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme.lower() != "https":
        raise VerificationError("Python package index URL must use HTTPS")
    if not parsed.hostname:
        raise VerificationError("Python package index URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise VerificationError("Python package index URL must not include userinfo")
    return candidate


def safe_pip_index_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    host = parsed.hostname or "<invalid-host>"
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is not None:
        host = f"{host}:{port}"
    query_names = sorted(
        {
            key
            for key, _ in urllib.parse.parse_qsl(
                parsed.query, keep_blank_values=True
            )
        }
    )
    safe_query = "&".join(f"{key}=<redacted>" for key in query_names)
    return urllib.parse.urlunsplit(
        (parsed.scheme, host, parsed.path, safe_query, "")
    )


def discover_pip_index_url(
    explicit: str | None,
    *,
    environ: dict[str, str] | os._Environ[str] | None = None,
    pip_config_reader: Any | None = None,
) -> tuple[str, str]:
    environment = os.environ if environ is None else environ
    if explicit:
        return validate_pip_index_url(explicit), "command-line"
    if environment.get("PIP_INDEX_URL"):
        return validate_pip_index_url(environment["PIP_INDEX_URL"]), "environment"

    if pip_config_reader is None:
        def pip_config_reader() -> subprocess.CompletedProcess[str]:
            return _run_command(
                [sys.executable, "-m", "pip", "config", "get", "global.index-url"],
                operation="read host pip global.index-url",
                cwd=_PYTHON_ROOT.parent,
                capture_output=True,
                text=True,
                check=False,
            )

    configured = pip_config_reader()
    if configured.returncode == 0 and configured.stdout.strip():
        return validate_pip_index_url(configured.stdout.strip()), "host-pip-config"
    return _DEFAULT_PIP_INDEX_URL, "default"


def validate_npm_registry_url(value: str) -> str:
    candidate = value.strip()
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme.lower() != "https":
        raise VerificationError("npm registry URL must use HTTPS")
    if not parsed.hostname:
        raise VerificationError("npm registry URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise VerificationError("npm registry URL must not include userinfo")
    return candidate


def discover_npm_registry_url(
    explicit: str | None,
    *,
    environ: dict[str, str] | os._Environ[str] | None = None,
    npm_config_reader: Any | None = None,
) -> tuple[str, str]:
    environment = os.environ if environ is None else environ
    if explicit:
        return validate_npm_registry_url(explicit), "command-line"
    if environment.get("NPM_CONFIG_REGISTRY"):
        return (
            validate_npm_registry_url(environment["NPM_CONFIG_REGISTRY"]),
            "environment",
        )

    if npm_config_reader is None:
        def npm_config_reader() -> subprocess.CompletedProcess[str]:
            return _run_command(
                ["npm", "config", "get", "registry"],
                operation="read host npm registry",
                cwd=_PYTHON_ROOT.parent / "frontend",
                capture_output=True,
                text=True,
                check=False,
            )

    configured = npm_config_reader()
    if configured.returncode == 0 and configured.stdout.strip():
        return validate_npm_registry_url(configured.stdout.strip()), "host-npm-config"
    return _DEFAULT_NPM_REGISTRY_URL, "default"


def _safe_command(command: list[str]) -> str:
    safe: list[str] = []
    redact_next_build_arg = False
    for item in command:
        if redact_next_build_arg:
            if item.startswith(("PIP_INDEX_URL=", "NPM_CONFIG_REGISTRY=")):
                raw = item.split("=", 1)[1]
                item = f"{item.split('=', 1)[0]}={safe_pip_index_url(raw)}"
            redact_next_build_arg = False
        safe.append(item)
        if item == "--build-arg":
            redact_next_build_arg = True
    return " ".join(safe)


def _redact_sensitive_text(
    value: str, sensitive_values: dict[str, str] | None = None
) -> str:
    redacted = value
    for raw, safe in (sensitive_values or {}).items():
        if raw:
            redacted = redacted.replace(raw, safe)
    return redacted


def _http_stage(url: str) -> str:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host == "management.azure.com":
        return "ARM"
    if host == "api.fabric.microsoft.com":
        return "Fabric"
    if host == "api.powerbi.com":
        return "Power BI"
    if host.endswith(".azurecr.io"):
        return "ACR"
    return "HTTP"


def _retry_after_seconds(headers: Any, now: datetime | None = None) -> float | None:
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(value))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            current = now or datetime.now(timezone.utc)
            return max(0.0, (retry_at - current).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _is_transient_transport_error(exc: BaseException) -> bool:
    candidate: BaseException | Any = exc
    if isinstance(candidate, urllib.error.URLError):
        candidate = candidate.reason
    if isinstance(
        candidate,
        (
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
            http.client.RemoteDisconnected,
            TimeoutError,
            socket.timeout,
        ),
    ):
        return True
    return isinstance(candidate, OSError) and getattr(candidate, "winerror", None) in {
        10053,
        10054,
        10060,
    }


def _retry_delay(attempt: int, headers: Any = None) -> float:
    retry_after = _retry_after_seconds(headers)
    if retry_after is not None:
        return min(retry_after, _HTTP_BACKOFF_CAP_SECONDS)
    return min(
        _HTTP_BACKOFF_SECONDS * (2 ** (attempt - 1)),
        _HTTP_BACKOFF_CAP_SECONDS,
    )


def _urlopen_with_retry(
    request: urllib.request.Request,
    *,
    stage: str,
    retry_safe: bool,
    timeout: float = 180,
):
    attempts = _HTTP_MAX_ATTEMPTS if retry_safe else 1
    method = request.get_method()
    safe_url = _safe_url(request.full_url)
    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            transient = exc.code in _TRANSIENT_HTTP_STATUS
            if transient and attempt < attempts:
                time.sleep(_retry_delay(attempt, exc.headers))
                continue
            detail = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
                error_payload = json.loads(error_body)
                error = error_payload.get("error", error_payload)
                code = str(error.get("code", "")).strip()
                message = str(error.get("message", "")).strip()
                if code or message:
                    detail = f"; service_error={code}: {message}"[:1200]
            except (AttributeError, json.JSONDecodeError, UnicodeDecodeError):
                pass
            raise VerificationError(
                f"{stage}: {method} {safe_url} failed with HTTP {exc.code} "
                f"after {attempt} attempt(s){detail}"
            ) from exc
        except (
            urllib.error.URLError,
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
            http.client.RemoteDisconnected,
            TimeoutError,
            socket.timeout,
        ) as exc:
            transient = _is_transient_transport_error(exc)
            if transient and attempt < attempts:
                time.sleep(_retry_delay(attempt))
                continue
            reason = type(
                exc.reason if isinstance(exc, urllib.error.URLError) else exc
            ).__name__
            raise VerificationError(
                f"{stage}: {method} {safe_url} failed with {reason} "
                f"after {attempt} attempt(s)"
            ) from exc
    raise AssertionError("HTTP retry loop exited unexpectedly")


class LiveRuntime:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.env = _azd_values()
        self.endpoint = args.cosmos_endpoint or os.environ.get("COSMOSDB_ENDPOINT") or self.env.get("COSMOSDB_ENDPOINT", "")
        self.database_name = args.database or os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")
        self.tenant_id = args.azure_tenant or self.env.get("AZURE_TENANT_ID", "")
        self.subscription_id = args.subscription or self.env.get("AZURE_SUBSCRIPTION_ID", "")
        self.resource_group = args.resource_group or self.env.get("RG_NAME", "")
        self.account = self.endpoint.replace("https://", "").split(".")[0] if self.endpoint else ""
        if not all((self.endpoint, self.tenant_id, self.subscription_id, self.resource_group, self.account)):
            raise VerificationError("azd/Cosmos identity configuration is incomplete")
        from azure.cosmos import CosmosClient
        from src.app.services import demo_data, optimization_insights, optimization_policy

        providers = []
        if os.name == "nt":
            providers.append(AzurePowerShellTokenProvider())
        providers.extend((DefaultCredentialTokenProvider(), AzureCliTokenProvider()))
        self.token_provider = ChainedTokenProvider(providers)
        credential = AzurePowerShellTokenCredential(self.token_provider)
        self.demo_data = demo_data
        self.optimization_insights = optimization_insights
        self.optimization_policy = optimization_policy
        self.database = CosmosClient(self.endpoint, credential).get_database_client(self.database_name)
        self.backup_store = CosmosBackupStore(
            self.database,
            endpoint=self.endpoint,
            database_name=self.database_name,
            policy_service=self.optimization_policy,
        )
        self._protected_before: dict[str, Any] | None = None
        self._deployment_inventory: dict[str, Any] | None = None
        self._deployment_mutated = False

    def git_head(self) -> str:
        completed = _run_command(
            ["git", "rev-parse", "HEAD"],
            operation="read Git HEAD",
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    def identity_preflight(self) -> dict[str, Any]:
        preflight = IdentityPreflight(
            IdentityIntent(
                tenant_id=self.tenant_id,
                subscription_id=self.subscription_id,
                cosmos_account=self.account,
                cosmos_endpoint=self.endpoint,
            ),
            self.token_provider,
            self._arm_identity,
        )
        return preflight.run()

    def _request_json(
        self,
        method: str,
        url: str,
        resource: str,
        payload: Any = None,
        *,
        allow_absent: bool = False,
        poll_async: bool = True,
        retry_safe: bool | None = None,
        stage: str | None = None,
    ) -> dict[str, Any] | None:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request_path = urllib.parse.urlsplit(url).path.lower()
        if retry_safe is None:
            retry_safe = method in {"GET", "HEAD"} or (
                method == "POST"
                and request_path.endswith(("/getdefinition", "/executequeries"))
            )
        operation_stage = stage or _http_stage(url)
        request = urllib.request.Request(
            url,
            method=method,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token_provider.get_token(resource)}",
                "Content-Type": "application/json",
            },
        )
        try:
            with _urlopen_with_retry(
                request,
                stage=operation_stage,
                retry_safe=retry_safe,
            ) as response:
                body = response.read()
                result = json.loads(body.decode("utf-8")) if body else {}
                location = (
                    response.headers.get("Azure-AsyncOperation")
                    or response.headers.get("Operation-Location")
                    or response.headers.get("Location")
                )
                status = response.status
        except VerificationError as exc:
            cause = exc.__cause__
            if (
                allow_absent
                and isinstance(cause, urllib.error.HTTPError)
                and cause.code == 404
            ):
                return None
            raise
        if status == 202 and location and poll_async:
            deadline = time.monotonic() + min(self.args.timeout_seconds, 600)
            while time.monotonic() <= deadline:
                poll_request = urllib.request.Request(
                    location,
                    method="GET",
                    headers={
                        "Authorization": f"Bearer {self.token_provider.get_token(resource)}",
                        "Content-Type": "application/json",
                    },
                )
                try:
                    poll_response_context = _urlopen_with_retry(
                        poll_request,
                        stage=f"{operation_stage} LRO poll",
                        retry_safe=True,
                    )
                except VerificationError as exc:
                    cause = exc.__cause__
                    if (
                        isinstance(cause, urllib.error.HTTPError)
                        and cause.code in {404, 410}
                    ):
                        return {**result, "operation_status_unavailable": True}
                    raise
                with poll_response_context as poll_response:
                    poll_body = poll_response.read()
                    poll = json.loads(poll_body.decode("utf-8")) if poll_body else {}
                    result_location = poll_response.headers.get("Location")
                state = str(poll.get("status", "")).lower()
                if state in {"succeeded", "completed"}:
                    if result_location:
                        return self._request_json(
                            "GET",
                            result_location,
                            resource,
                            stage=f"{operation_stage} LRO result",
                        )
                    return poll
                if state in {"failed", "cancelled"}:
                    raise VerificationError(
                        f"{operation_stage} LRO {state}: "
                        f"{method} {_safe_url(url)}"
                    )
                time.sleep(2)
            raise VerificationError(
                f"{operation_stage} LRO timed out: {method} {_safe_url(url)}"
            )
        return result

    def _arm_identity(self) -> dict[str, Any]:
        account = self._request_json(
            "GET",
            (
                f"https://management.azure.com/subscriptions/{self.subscription_id}"
                f"/resourceGroups/{self.resource_group}/providers/Microsoft.DocumentDB"
                f"/databaseAccounts/{self.account}?api-version=2024-05-15"
            ),
            "https://management.azure.com/",
        )
        subscription = self._request_json(
            "GET",
            f"https://management.azure.com/subscriptions/{self.subscription_id}?api-version=2022-12-01",
            "https://management.azure.com/",
        )
        return {
            "tenant_id": subscription.get("tenantId") or self.tenant_id,
            "subscription_id": str(subscription["id"]).rsplit("/", 1)[-1],
            "cosmos_account": account["name"],
            "cosmos_endpoint": account["properties"]["documentEndpoint"],
        }

    def capture_backup(self, path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.backup_store.capture(path, arguments)
        self._protected_before = result["protected"]
        return result

    def _fabric_definition(
        self, workspace_id: str, collection: str, item_id: str | None
    ) -> dict[str, Any]:
        if not workspace_id:
            return {
                "present": False,
                "item_id": item_id,
                "collection": collection,
                "reason": "workspace-id-not-persisted",
            }
        if not item_id:
            return {
                "present": False,
                "item_id": None,
                "collection": collection,
                "reason": "id-not-persisted",
            }
        definition = self._request_json(
            "POST",
            (
                f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}"
                f"/{collection}/{item_id}/getDefinition"
            ),
            "https://api.fabric.microsoft.com/",
            {},
            allow_absent=True,
        )
        if definition is None:
            return {
                "present": False,
                "item_id": item_id,
                "collection": collection,
                "reason": "not-found",
            }
        payload = definition.get("definition", definition)
        return {
            "present": True,
            "item_id": item_id,
            "collection": collection,
            "definition": payload,
            "definition_sha256": sha256_json(payload),
        }

    def capture_deployment_inventory(self, backup_path: Path) -> dict[str, Any]:
        flags = {
            key: self.env.get(key)
            for key in ("DEPLOY_ANALYTICS", "DEPLOY_GSI", "DEPLOY_HOSTED_APP")
        }
        ids = {
            key: self.env.get(key)
            for key in (
                "FABRIC_WORKSPACE_ID",
                "FABRIC_MIRROR_ID",
                "FABRIC_NOTEBOOK_ID",
                "FABRIC_DEMO_TENANTS_PIPELINE_ID",
                "FABRIC_UDF_ID",
                "FABRIC_SEMANTIC_MODEL_ID",
                "FABRIC_REPORT_ID",
            )
        }
        apps = self._request_json(
            "GET",
            (
                f"https://management.azure.com/subscriptions/{self.subscription_id}"
                f"/resourceGroups/{self.resource_group}/providers/Microsoft.App/containerApps"
                "?api-version=2024-03-01"
            ),
            "https://management.azure.com/",
        )
        container_apps = []
        for app in apps.get("value", []):
            properties = app.get("properties", {})
            template = properties.get("template", {})
            images = [item.get("image") for item in template.get("containers", [])]
            revisions = self._request_json(
                "GET",
                (
                    f"https://management.azure.com{app['id']}/revisions"
                    "?api-version=2024-03-01"
                ),
                "https://management.azure.com/",
            )
            container_apps.append(
                {
                    "name": app.get("name"),
                    "resource_id": app.get("id"),
                    "location": app.get("location"),
                    "latest_revision": properties.get("latestRevisionName"),
                    "traffic": properties.get("configuration", {}).get("ingress", {}).get("traffic", []),
                    "template": template,
                    "configuration": properties.get("configuration", {}),
                    "revisions": revisions.get("value", []),
                    "images": images,
                    "digests": [
                        image.split("@", 1)[1]
                        for image in images
                        if image and "@sha256:" in image
                    ],
                    "health": properties.get("runningStatus") or properties.get("provisioningState"),
                }
            )
        workspace_id = ids.get("FABRIC_WORKSPACE_ID")
        definitions = {
            "notebook": self._fabric_definition(
                workspace_id, "notebooks", ids.get("FABRIC_NOTEBOOK_ID")
            ),
            "pipeline": self._fabric_definition(
                workspace_id,
                "dataPipelines",
                ids.get("FABRIC_DEMO_TENANTS_PIPELINE_ID"),
            ),
            "semantic_model": self._fabric_definition(
                workspace_id, "semanticModels", ids.get("FABRIC_SEMANTIC_MODEL_ID")
            ),
            "report": self._fabric_definition(
                workspace_id, "reports", ids.get("FABRIC_REPORT_ID")
            ),
        }
        inventory = {
            "schema_version": 1,
            "capture_utc": datetime.now(timezone.utc).isoformat(),
            "azd": {
                "flags": flags,
                "environment": self.env.get("AZURE_ENV_NAME"),
                "frontend_uri": self.env.get("FRONTEND_URI"),
                "tenant_id": self.tenant_id,
                "subscription_id": self.subscription_id,
                "service_images": {
                    key: self.env.get(key)
                    for key in (
                        "SERVICE_API_IMAGE_NAME",
                        "SERVICE_MCP_SERVER_IMAGE_NAME",
                        "SERVICE_FRONTEND_IMAGE_NAME",
                    )
                },
            },
            "container_apps": container_apps,
            "fabric": {
                "ids": ids,
                "completed_notebook": "analytics/fabric/ConversionFunnelReverseETL_solution.ipynb",
                "sequential_pipeline": "RefreshAllDemoTenants",
                "mounted_tables": list(MIRROR_TABLES),
                "definitions": definitions,
            },
        }
        inventory_path = backup_path.with_name(
            f"{backup_path.stem}.deployment-inventory.json"
        )
        inventory["inventory_receipt"] = write_durable_json(inventory_path, inventory)
        self._deployment_inventory = copy.deepcopy(inventory)
        return inventory

    def deploy_existing_topology(self) -> dict[str, Any]:
        if self._deployment_inventory is None:
            raise VerificationError("deployment inventory must be captured before deployment")
        transport = self._deployment_transport()
        if transport == "azd":
            azd = _run_command(
                ["azd", "deploy", "--all"],
                operation="deploy existing topology with azd",
                cwd=_PYTHON_ROOT.parent,
                capture_output=True,
                text=True,
                check=False,
            )
            if azd.returncode:
                self._deployment_mutated = self._container_apps_differ_from_inventory()
                raise VerificationError(
                    f"azd deploy --all failed with exit {azd.returncode}: "
                    f"{(azd.stderr or azd.stdout).strip()[:500]}"
                )
            self._deployment_mutated = True
            app_deployment: dict[str, Any] = {
                "status": "PASS",
                "transport": "azd",
                "command": "azd deploy --all",
            }
        else:
            app_deployment = self._deploy_container_apps_direct()

        fabric_deployment = self._deploy_completed_fabric()
        result = {
            "status": "PASS",
            "transport": transport,
            "container_apps": app_deployment,
            "fabric_solution": True,
            **fabric_deployment,
        }
        receipt_path = Path(
            self._deployment_inventory["inventory_receipt"]["path"]
        ).with_name("controlled-demo4-deployment-receipt.json")
        result["receipt"] = write_durable_json(receipt_path, result)
        return result

    def deployment_mutated(self) -> bool:
        return self._deployment_mutated

    def _deployment_transport(self) -> str:
        if self.args.deployment_transport == "direct":
            return "direct"
        if shutil.which("azd") is None:
            if self.args.deployment_transport == "azd":
                raise VerificationError(
                    "check azd authentication for deployment transport: "
                    f"executable not found: 'azd'; cwd={_PYTHON_ROOT.parent}"
                )
            return "direct"
        azd_status = _run_command(
            ["azd", "auth", "login", "--check-status"],
            operation="check azd authentication for deployment transport",
            cwd=_PYTHON_ROOT.parent,
            capture_output=True,
            text=True,
            check=False,
        )
        cli_tenant = ""
        cli_subscription = ""
        if azd_status.returncode == 0:
            if shutil.which("az") is None:
                if self.args.deployment_transport == "azd":
                    raise VerificationError(
                        "read Azure CLI account for deployment transport: "
                        f"executable not found: 'az'; cwd={_PYTHON_ROOT.parent}"
                    )
                return "direct"
            account = _run_command(
                ["az", "account", "show", "--output", "json"],
                operation="read Azure CLI account for deployment transport",
                cwd=_PYTHON_ROOT.parent,
                capture_output=True,
                text=True,
                check=False,
            )
            if account.returncode == 0:
                try:
                    payload = json.loads(account.stdout)
                    cli_tenant = str(payload.get("tenantId", ""))
                    cli_subscription = str(payload.get("id", ""))
                except json.JSONDecodeError:
                    pass
        return select_deployment_transport(
            self.args.deployment_transport,
            azd_authenticated=azd_status.returncode == 0,
            cli_tenant=cli_tenant,
            cli_subscription=cli_subscription,
            intended_tenant=self.tenant_id,
            intended_subscription=self.subscription_id,
        )

    @staticmethod
    def _image_repository(image: str) -> str:
        return container_image_with_tag(image, "__tag__").rsplit(":", 1)[0]

    def _service_images(self) -> dict[str, dict[str, str]]:
        definitions = {
            "api": ("SERVICE_API_IMAGE_NAME", "Dockerfile.api"),
            "mcp-server": ("SERVICE_MCP_SERVER_IMAGE_NAME", "Dockerfile.mcp"),
            "frontend": ("SERVICE_FRONTEND_IMAGE_NAME", "Dockerfile.frontend"),
        }
        result = {}
        for service, (variable, dockerfile) in definitions.items():
            image = self.env.get(variable, "")
            if not image:
                raise VerificationError(f"azd environment is missing {variable}")
            result[service] = {
                "variable": variable,
                "dockerfile": dockerfile,
                "current_image": image,
            }
        return result

    def _receipt_tag(self) -> str:
        seed = {
            "capture_utc": self._deployment_inventory["capture_utc"],
            "git_sha": self.git_head(),
            "environment": self.env.get("AZURE_ENV_NAME", ""),
        }
        suffix = hashlib.sha256(
            json.dumps(seed, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        return f"brief-f-{seed['git_sha'][:12]}-{suffix}"

    def _acr_access_token(self, repositories: list[str]) -> tuple[str, str]:
        login_server = self.env.get("AZURE_CONTAINER_REGISTRY_ENDPOINT", "")
        registry_name = self.env.get("AZURE_CONTAINER_REGISTRY_NAME", "")
        if not login_server or not registry_name:
            raise VerificationError("ACR endpoint/name is missing from the azd environment")
        login_server = login_server.removeprefix("https://").rstrip("/")
        arm_token = self.token_provider.get_token("https://management.azure.com/")
        exchange = urllib.request.Request(
            f"https://{login_server}/oauth2/exchange",
            method="POST",
            data=urllib.parse.urlencode(
                {
                    "grant_type": "access_token",
                    "service": login_server,
                    "tenant": self.tenant_id,
                    "access_token": arm_token,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with _urlopen_with_retry(
                exchange,
                stage="ACR refresh-token exchange",
                retry_safe=True,
            ) as response:
                refresh_token = json.loads(response.read().decode("utf-8"))[
                    "refresh_token"
                ]
            scopes = [
                ("scope", f"repository:{repository}:pull,push")
                for repository in repositories
            ]
            access_request = urllib.request.Request(
                f"https://{login_server}/oauth2/token",
                method="POST",
                data=urllib.parse.urlencode(
                    [
                        ("grant_type", "refresh_token"),
                        ("service", login_server),
                        *scopes,
                        ("refresh_token", refresh_token),
                    ]
                ).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with _urlopen_with_retry(
                access_request,
                stage="ACR access-token exchange",
                retry_safe=True,
            ) as response:
                access_token = json.loads(response.read().decode("utf-8"))[
                    "access_token"
                ]
        except KeyError as exc:
            raise VerificationError(
                "ACR OAuth exchange returned a response without the required token"
            ) from exc
        except VerificationError:
            raise
        return login_server, access_token

    @staticmethod
    def _run_docker(
        command: list[str],
        *,
        operation: str = "run Docker command",
        input_text: str | None = None,
        sensitive_values: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        completed = _run_command(
            command,
            operation=operation,
            cwd=_PYTHON_ROOT.parent,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode:
            output = _redact_sensitive_text(
                (completed.stderr or completed.stdout).strip()[:1000],
                sensitive_values,
            )
            raise VerificationError(
                f"{operation} failed ({completed.returncode}); cwd={_PYTHON_ROOT.parent}; "
                f"command={_safe_command(command)}: {output}"
            )
        return completed

    def _deploy_container_apps_direct(self) -> dict[str, Any]:
        build_root = _PYTHON_ROOT.parent.resolve()
        pip_index_url, pip_index_source = discover_pip_index_url(
            getattr(self.args, "pip_index_url", None)
        )
        safe_index_url = safe_pip_index_url(pip_index_url)
        npm_registry_url, npm_registry_source = discover_npm_registry_url(
            getattr(self.args, "npm_registry_url", None)
        )
        safe_npm_registry_url = safe_pip_index_url(npm_registry_url)
        self._run_docker(
            ["docker", "info", "--format", "{{json .ServerVersion}}"],
            operation="check Docker daemon availability",
        )
        services = self._service_images()
        tag = self._receipt_tag()
        for details in services.values():
            details["new_image"] = container_image_with_tag(
                details["current_image"], tag
            )
        repositories = [
            self._image_repository(details["new_image"]).split("/", 1)[-1]
            for details in services.values()
        ]
        login_server, access_token = self._acr_access_token(repositories)
        self._run_docker(
            [
                "docker",
                "login",
                login_server,
                "--username",
                "00000000-0000-0000-0000-000000000000",
                "--password-stdin",
            ],
            operation=f"authenticate Docker to ACR {login_server}",
            input_text=access_token,
        )

        self._stage_analytics_portal()

        for details in services.values():
            dockerfile = (build_root / details["dockerfile"]).resolve()
            if not dockerfile.is_file():
                raise VerificationError(
                    f"stage Docker build: Dockerfile not found: {dockerfile}; "
                    f"build_context={build_root}"
                )
            self._run_docker(
                [
                    "docker",
                    "build",
                    "--build-arg",
                    f"PIP_INDEX_URL={pip_index_url}",
                    "--build-arg",
                    f"NPM_CONFIG_REGISTRY={npm_registry_url}",
                    "--file",
                    str(dockerfile),
                    "--tag",
                    details["new_image"],
                    str(build_root),
                ],
                operation=f"build {details['new_image']} from {dockerfile}",
                sensitive_values={
                    pip_index_url: safe_index_url,
                    npm_registry_url: safe_npm_registry_url,
                },
            )

        for details in services.values():
            pushed = self._run_docker(
                ["docker", "push", details["new_image"]],
                operation=f"push image {details['new_image']}",
            )
            match = re.search(
                r"digest:\s*(sha256:[0-9a-f]{64})",
                f"{pushed.stdout}\n{pushed.stderr}",
                re.IGNORECASE,
            )
            if not match:
                raise VerificationError(
                    f"docker push did not report a digest for {details['new_image']}"
                )
            details["digest"] = match.group(1).lower()

        updates = self._update_existing_container_apps(services)
        for details in services.values():
            completed = _run_command(
                ["azd", "env", "set", details["variable"], details["new_image"]],
                operation=f"persist deployed image in azd variable {details['variable']}",
                cwd=_PYTHON_ROOT.parent,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode:
                raise VerificationError(
                    f"failed to update {details['variable']} in the azd environment"
                )
            self.env[details["variable"]] = details["new_image"]
        return {
            "status": "PASS",
            "transport": "direct",
            "tag": tag,
            "pip_index": {
                "source": pip_index_source,
                "url": safe_index_url,
            },
            "npm_registry": {
                "source": npm_registry_source,
                "url": safe_npm_registry_url,
            },
            "images": services,
            "updates": updates,
        }

    @staticmethod
    def _stage_analytics_portal() -> None:
        build_root = _PYTHON_ROOT.parent.resolve()
        portal = build_root / "analytics-portal"
        source = (_REPO_ROOT / "analytics" / "dashboard" / "index.html").resolve()
        destination = portal / "index.html"
        if not source.is_file():
            raise VerificationError(
                f"stage Analytics Portal: source file not found: {source}; "
                f"destination={destination}; build_context={build_root}"
            )
        try:
            portal.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
        except FileNotFoundError as exc:
            raise VerificationError(
                f"stage Analytics Portal: file path not found; source={source}; "
                f"destination={destination}; path={exc.filename or '<unknown>'}"
            ) from exc

    def _update_existing_container_apps(
        self, services: dict[str, dict[str, str]]
    ) -> list[dict[str, Any]]:
        inventory_apps = self._deployment_inventory.get("container_apps", [])
        assignments: dict[str, dict[str, Any]] = {}
        for service, details in services.items():
            repository = self._image_repository(details["current_image"])
            matches = [
                app
                for app in inventory_apps
                if any(
                    self._image_repository(image or "") == repository
                    for image in app.get("images", [])
                )
            ]
            if len(matches) != 1:
                raise VerificationError(
                    f"expected one existing Container App for {service}, found {len(matches)}"
                )
            assignments[service] = matches[0]

        updates = []
        for service, app in assignments.items():
            details = services[service]
            observed = self._request_json(
                "GET",
                f"https://management.azure.com{app['resource_id']}?api-version=2024-03-01",
                "https://management.azure.com/",
            )
            properties = observed.get("properties", {})
            if sha256_json(properties.get("template", {})) != sha256_json(
                app.get("template", {})
            ):
                raise VerificationError(
                    f"{app['name']} template drifted after rollback inventory capture"
                )
            repository = self._image_repository(details["current_image"])
            current_app_images = [
                item.get("image")
                for item in properties["template"].get("containers", [])
                if self._image_repository(item.get("image", "")) == repository
            ]
            if len(current_app_images) != 1:
                raise VerificationError(
                    f"{app['name']} does not have exactly one image field for {service}"
                )
            updated_template = update_template_image(
                properties["template"], current_app_images[0], details["new_image"]
            )
            revision_suffix = details["new_image"].rsplit(":", 1)[-1]
            max_suffix_length = 54 - len(app["name"]) - 2
            if len(revision_suffix) > max_suffix_length:
                digest_length = min(12, max_suffix_length - 3)
                revision_suffix = (
                    "bf-"
                    + hashlib.sha256(revision_suffix.encode("utf-8")).hexdigest()[
                        :digest_length
                    ]
                )
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}[a-z0-9]", revision_suffix):
                raise VerificationError(
                    f"generated image tag is not a valid Container App revision suffix: "
                    f"{revision_suffix}"
                )
            if len(app["name"]) + 2 + len(revision_suffix) > 54:
                raise VerificationError(
                    f"generated revision name exceeds the Container Apps 54-character limit: "
                    f"{app['name']}--{revision_suffix}"
                )
            updated_template["revisionSuffix"] = revision_suffix
            body = {
                "location": observed.get("location"),
                "properties": {
                    "configuration": properties.get("configuration", {}),
                    "template": updated_template,
                },
            }
            try:
                self._request_json(
                    "PATCH",
                    f"https://management.azure.com{app['resource_id']}?api-version=2024-03-01",
                    "https://management.azure.com/",
                    body,
                    poll_async=False,
                    retry_safe=True,
                    stage=f"ARM update Container App {app['name']}",
                )
            except Exception:
                self._deployment_mutated = self._container_apps_differ_from_inventory()
                raise
            self._deployment_mutated = True
            health = self._wait_for_container_app(
                app["resource_id"], updated_template, details["new_image"]
            )
            updates.append({"service": service, "app": app["name"], **health})
        return updates

    def _wait_for_container_app(
        self, resource_id: str, expected_template: dict[str, Any], expected_image: str
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.args.timeout_seconds
        last: dict[str, Any] = {}
        while time.monotonic() <= deadline:
            app = self._request_json(
                "GET",
                f"https://management.azure.com{resource_id}?api-version=2024-03-01",
                "https://management.azure.com/",
            )
            properties = app.get("properties", {})
            last = {
                "provisioning_state": properties.get("provisioningState"),
                "running_status": properties.get("runningStatus"),
                "latest_revision": properties.get("latestRevisionName"),
                "traffic": properties.get("configuration", {})
                .get("ingress", {})
                .get("traffic", []),
            }
            image_matches = any(
                item.get("image") == expected_image
                for item in properties.get("template", {}).get("containers", [])
            )
            if (
                image_matches
                and str(last["provisioning_state"]).lower() == "succeeded"
                and last["latest_revision"]
            ):
                revisions = self._request_json(
                    "GET",
                    f"https://management.azure.com{resource_id}/revisions?api-version=2024-03-01",
                    "https://management.azure.com/",
                )
                latest = next(
                    (
                        revision
                        for revision in revisions.get("value", [])
                        if revision.get("name") == last["latest_revision"]
                    ),
                    {},
                )
                revision_properties = latest.get("properties", {})
                last["revision_health"] = (
                    revision_properties.get("healthState")
                    or revision_properties.get("runningState")
                    or revision_properties.get("provisioningState")
                )
                if str(last["revision_health"]).lower() in {
                    "healthy",
                    "running",
                    "succeeded",
                }:
                    last["image"] = expected_image
                    return last
            time.sleep(self.args.poll_interval)
        raise VerificationError(
            f"Container App did not reach the expected healthy revision: {last}"
        )

    def _container_apps_differ_from_inventory(self) -> bool:
        for app in self._deployment_inventory.get("container_apps", []):
            observed = self._request_json(
                "GET",
                f"https://management.azure.com{app['resource_id']}?api-version=2024-03-01",
                "https://management.azure.com/",
            )
            if sha256_json(observed.get("properties", {}).get("template", {})) != sha256_json(
                app.get("template", {})
            ):
                return True
        return False

    def _deploy_completed_fabric(self) -> dict[str, Any]:
        state_path = _REPO_ROOT / "analytics" / "fabric" / ".provision-fabric.local.json"
        if not state_path.is_file():
            raise VerificationError(
                f"stage completed Fabric deployment: state file not found: {state_path}"
            )
        try:
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            raise VerificationError(
                f"stage completed Fabric deployment: state file disappeared: {state_path}"
            ) from exc
        connection_id = state.get("ConnectionId")
        workspace_name = state.get("WorkspaceName")
        if not connection_id or not workspace_name:
            raise VerificationError(
                "persisted Fabric connection ID/workspace name is missing"
            )
        provision_script = (
            _REPO_ROOT / "analytics" / "fabric" / "Provision-Fabric.ps1"
        ).resolve()
        if not provision_script.is_file():
            raise VerificationError(
                f"stage completed Fabric deployment: script not found: {provision_script}"
            )
        commands = []
        for phase in ("2", "3"):
            command = [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(provision_script),
                "-WorkshopRoot",
                str(_PYTHON_ROOT.parent),
                "-WorkspaceName",
                workspace_name,
                "-ConnectionId",
                connection_id,
                "-Solution",
                "-Phase",
                phase,
            ]
            fabric = _run_command(
                command,
                operation=f"deploy completed Fabric phase {phase}",
                cwd=_REPO_ROOT,
                check=False,
            )
            commands.append({"phase": phase, "exit_code": fabric.returncode})
            if fabric.returncode:
                raise VerificationError(
                    f"deploy completed Fabric phase {phase} failed with exit "
                    f"{fabric.returncode}; script={provision_script}; cwd={_REPO_ROOT}"
                )
        self.env = _azd_values()
        persisted = {
            key: self.env.get(key)
            for key in (
                "FABRIC_NOTEBOOK_ID",
                "FABRIC_DEMO_TENANTS_PIPELINE_ID",
                "FABRIC_SEMANTIC_MODEL_ID",
                "FABRIC_REPORT_ID",
            )
        }
        if not all(persisted.values()):
            raise VerificationError(f"Fabric deployment did not persist all item IDs: {persisted}")
        return {
            "fabric_phases": commands,
            "persisted_ids": persisted,
        }

    def reset(self) -> dict[str, Any]:
        return self.demo_data.reset_controlled_demo4(
            db=self.database,
            fixture_version=self.args.fixture,
            anchor=self.args.anchor,
            count=self.args.count,
            backup_dir=self.args.backup_dir,
        )

    def direct_snapshot(self) -> dict[str, Any]:
        tenants: dict[str, dict[str, list[dict[str, Any]]]] = {}
        funnel: dict[str, Any] = {}
        for tenant in TENANTS:
            tenants[tenant] = {
                name: [
                    row
                    for row in _all_rows(
                        self.database.get_container_client(name), tenant
                    )
                    if is_controlled_fixture_row(name, row, tenant)
                ]
                for name in (*COHORT_CONTAINERS, *DERIVED_CONTAINERS)
            }
            sessions = tenants[tenant]["Sessions"]
            stages = {
                "engaged": len(sessions),
                "searched": sum(row.get("session_outcome") != "no_engagement" for row in sessions),
                "planned": sum(row.get("session_outcome") in {"converted", "cart_abandon"} for row in sessions),
                "confirmed": len(tenants[tenant]["Trips"]),
            }
            causes: dict[str, int] = {}
            for row in sessions:
                outcome = row.get("session_outcome")
                if outcome != "converted":
                    causes[outcome] = causes.get(outcome, 0) + 1
            largest = max(causes.items(), key=lambda item: item[1])
            funnel[tenant] = {
                "stages": stages,
                "conversion_rate": round(stages["confirmed"] / stages["engaged"] * 100, 1),
                "largest_cause": {"name": largest[0], "count": largest[1]},
            }
        policies = {
            tenant: (
                self.optimization_policy.get_policy("model-selection", tenant) or {}
            )
            for tenant in TENANTS
        }
        protected = self.backup_store.protected_hashes()
        return {
            "tenants": tenants,
            "funnel": funnel,
            "evaluations": {
                tenant: evaluate_controlled_demo4(
                    self.database,
                    tenant,
                    policy_status=policies[tenant].get("status"),
                )
                for tenant in TENANTS
            },
            "policy_statuses": {
                tenant: policies[tenant].get("status") for tenant in TENANTS
            },
            "protected_unchanged": self._protected_before is None or protected == self._protected_before,
        }

    @staticmethod
    def _definition_table_names(definition: dict[str, Any]) -> list[str]:
        values: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, str):
                candidates = [value]
                try:
                    candidates.append(base64.b64decode(value).decode("utf-8"))
                except Exception:
                    pass
                for candidate in candidates:
                    for table in MIRROR_TABLES:
                        if table in candidate:
                            values.append(table)

        visit(definition)
        return sorted(set(values))

    @staticmethod
    def _query_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            return payload["results"][0]["tables"][0].get("rows", [])
        except (KeyError, IndexError, TypeError) as exc:
            raise VerificationError(f"Power BI executeQueries returned no rows: {payload}") from exc

    @staticmethod
    def _row_value(row: dict[str, Any], name: str) -> Any:
        for key, value in row.items():
            if key.strip("[]").split("[")[-1].rstrip("]") == name:
                return value
        return None

    def _execute_dax(self, query: str) -> list[dict[str, Any]]:
        workspace_id = self.env.get("FABRIC_WORKSPACE_ID")
        model_id = self.env.get("FABRIC_SEMANTIC_MODEL_ID")
        if not workspace_id or not model_id:
            raise VerificationError("persisted Fabric workspace/semantic-model IDs are required")
        payload = self._request_json(
            "POST",
            (
                f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}"
                f"/datasets/{model_id}/executeQueries"
            ),
            "https://analysis.windows.net/powerbi/api",
            {"queries": [{"query": query}], "serializerSettings": {"includeNulls": True}},
        )
        return self._query_rows(payload or {})

    def _built_in_semantic_evidence(self) -> dict[str, Any]:
        workspace_id = self.env.get("FABRIC_WORKSPACE_ID")
        mirror_id = self.env.get("FABRIC_MIRROR_ID")
        model_id = self.env.get("FABRIC_SEMANTIC_MODEL_ID")
        report_id = self.env.get("FABRIC_REPORT_ID")
        if not all((workspace_id, mirror_id, model_id, report_id)):
            raise VerificationError(
                "persisted Fabric workspace/mirror/model/report IDs are required"
            )
        report = self._request_json(
            "GET",
            (
                f"https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}"
                f"/reports/{report_id}"
            ),
            "https://analysis.windows.net/powerbi/api",
        )
        report_dataset_id = (report or {}).get("datasetId")
        if report_dataset_id and report_dataset_id.lower() != model_id.lower():
            raise VerificationError(
                "persisted Power BI report is not bound to the persisted semantic model"
            )
        mirror_definition = self._request_json(
            "POST",
            (
                f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}"
                f"/mirroredDatabases/{mirror_id}/getDefinition"
            ),
            "https://api.fabric.microsoft.com/",
            {},
        )
        mounted = self._definition_table_names(mirror_definition or {})
        queried_tables = (
            "OptimizationTurns",
            "Trips",
            "OptimizationInsights",
        )
        tenants: dict[str, Any] = {}
        exact = True
        stale_deleted = True
        for tenant in TENANTS:
            escaped = tenant.replace('"', '""')
            turns = self._execute_dax(
                "EVALUATE SELECTCOLUMNS("
                f"FILTER('TravelAssistant OptimizationTurns', "
                f"'TravelAssistant OptimizationTurns'[tenantId] = \"{escaped}\"),"
                "\"id\", 'TravelAssistant OptimizationTurns'[id],"
                "\"model_deployment\", 'TravelAssistant OptimizationTurns'[model_deployment],"
                "\"model_name\", 'TravelAssistant OptimizationTurns'[model_name],"
                "\"complexity_tier\", 'TravelAssistant OptimizationTurns'[complexity_tier])"
            )
            trips = self._execute_dax(
                "EVALUATE SELECTCOLUMNS("
                f"FILTER('TravelAssistant Trips', "
                f"'TravelAssistant Trips'[tenantId] = \"{escaped}\" "
                f"&& LEFT('TravelAssistant Trips'[sessionId], "
                f"LEN(\"{controlled_fixture_session_prefix(tenant)}\")) "
                f"= \"{controlled_fixture_session_prefix(tenant)}\"),"
                "\"id\", 'TravelAssistant Trips'[id])"
            )
            insights = self._execute_dax(
                "EVALUATE ROW(\"count\", COUNTROWS("
                f"FILTER('TravelAssistant OptimizationInsights', "
                f"'TravelAssistant OptimizationInsights'[tenantId] = \"{escaped}\")))"
            )
            expected = build_tenant_manifest(
                tenant,
                fixture_version=self.args.fixture,
                anchor=self.args.anchor,
                count=self.args.count,
            )
            turn_ids = sorted(str(self._row_value(row, "id")) for row in turns)
            trip_ids = sorted(str(self._row_value(row, "id")) for row in trips)
            expected_turn_ids = sorted(row["id"] for row in expected["OptimizationTurns"])
            expected_trip_ids = sorted(row["id"] for row in expected["Trips"])
            models = {
                (
                    self._row_value(row, "model_deployment"),
                    self._row_value(row, "model_name"),
                    self._row_value(row, "complexity_tier"),
                ): 0
                for row in turns
            }
            for row in turns:
                key = (
                    self._row_value(row, "model_deployment"),
                    self._row_value(row, "model_name"),
                    self._row_value(row, "complexity_tier"),
                )
                models[key] += 1
            insight_count = int(self._row_value(insights[0], "count") or 0)
            tenant_exact = (
                turn_ids == expected_turn_ids
                and trip_ids == expected_trip_ids
                and models == {("gpt-5.1", "gpt-5.1-2025-11-13", "default"): 200}
            )
            exact = exact and tenant_exact
            stale_deleted = stale_deleted and insight_count == 0
            tenants[tenant] = {
                "queried_counts": {
                    "OptimizationTurns": len(turn_ids),
                    "Trips": len(trip_ids),
                    "OptimizationInsights": insight_count,
                },
                "exact_ids": tenant_exact,
                "model_distribution": [
                    {
                        "model_deployment": key[0],
                        "model_name": key[1],
                        "complexity_tier": key[2],
                        "count": count,
                    }
                    for key, count in sorted(models.items(), key=lambda item: str(item[0]))
                ],
            }
        return {
            "mounted_tables": mounted,
            "queried_tables": list(queried_tables),
            "tenant_selections": list(TENANTS),
            "tenants": tenants,
            "exact_controlled_ids": exact,
            "stale_derived_rows_deleted": stale_deleted,
            "derived_visuals": "empty" if stale_deleted else "non-empty",
            "report": {
                "report_id": report_id,
                "semantic_model_id": model_id,
                "bound": not report_dataset_id
                or report_dataset_id.lower() == model_id.lower(),
            },
            "diagnostic": "source-backed Fabric definition plus Power BI executeQueries",
        }

    def _external_evidence(self, env_name: str) -> dict[str, Any]:
        command = os.environ.get(env_name, "")
        if not command:
            raise VerificationError(
                f"{env_name} is required and must emit verifier JSON; no fixed sleeps or inferred evidence"
            )
        return _redact_secrets(_run_json(shlex.split(command)))

    def poll_mirror(self, expectation: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
        attempts = {"value": 0}

        def probe() -> dict[str, Any]:
            attempts["value"] += 1
            if os.environ.get("CONTROLLED_DEMO_MIRROR_PROBE_COMMAND"):
                evidence = self._external_evidence("CONTROLLED_DEMO_MIRROR_PROBE_COMMAND")
            else:
                evidence = self._built_in_semantic_evidence()
            evidence["attempts"] = attempts["value"]
            return evidence

        return poll_mirror_convergence(
            probe,
            expectation,
            timeout_seconds=timeout_seconds,
            interval_seconds=self.args.poll_interval,
        )

    def verify_power_bi_baseline(self, tenants: tuple[str, ...]) -> dict[str, Any]:
        if os.environ.get("CONTROLLED_DEMO_POWERBI_PROBE_COMMAND"):
            evidence = self._external_evidence("CONTROLLED_DEMO_POWERBI_PROBE_COMMAND")
        else:
            evidence = self._built_in_semantic_evidence()
        observed = set(evidence.get("tenant_selections", []))
        if observed != set(tenants):
            raise VerificationError(f"Power BI evidence must cover both tenants, got {sorted(observed)}")
        if evidence.get("derived_visuals") not in ("empty", []):
            raise VerificationError("baseline Power BI derived visuals must be empty and expected")
        return {"status": "PASS", **evidence}

    def rollback_deployment(self, inventory: dict[str, Any]) -> dict[str, Any]:
        failures: list[str] = []
        restored: list[str] = []
        workspace_id = inventory.get("fabric", {}).get("ids", {}).get("FABRIC_WORKSPACE_ID")
        definitions = inventory.get("fabric", {}).get("definitions", {})
        for name, captured in definitions.items():
            if not captured.get("present"):
                if captured.get("item_id") and workspace_id:
                    try:
                        self._request_json(
                            "DELETE",
                            (
                                f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}"
                                f"/{captured.get('collection')}/{captured['item_id']}"
                            ),
                            "https://api.fabric.microsoft.com/",
                            allow_absent=True,
                        )
                        restored.append(f"{name}:absent")
                    except Exception as exc:
                        failures.append(f"{name} absence restore failed: {exc}")
                continue
            collection = captured["collection"]
            item_id = captured["item_id"]
            definition = captured["definition"]
            payload = definition.get("definition", definition)
            try:
                self._request_json(
                    "POST",
                    (
                        f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}"
                        f"/{collection}/{item_id}/updateDefinition"
                    ),
                    "https://api.fabric.microsoft.com/",
                    {"definition": payload},
                    retry_safe=True,
                    stage=f"Fabric restore definition {name}",
                )
                observed = self._fabric_definition(workspace_id, collection, item_id)
                if observed.get("definition_sha256") != captured.get("definition_sha256"):
                    failures.append(f"{name} definition hash verification failed")
                else:
                    restored.append(name)
            except Exception as exc:
                failures.append(f"{name} definition restore failed: {exc}")
        for app in inventory.get("container_apps", []):
            try:
                rollback_template = copy.deepcopy(app.get("template", {}))
                max_suffix_length = 54 - len(app["name"]) - 2
                suffix_seed = (
                    f"{app['name']}|{app.get('latest_revision')}|"
                    f"{datetime.now(timezone.utc).isoformat()}"
                )
                rollback_suffix = (
                    "rb-" + hashlib.sha256(suffix_seed.encode("utf-8")).hexdigest()[:12]
                )[:max_suffix_length].rstrip("-")
                rollback_template["revisionSuffix"] = rollback_suffix
                body = {
                    "location": app.get("location"),
                    "properties": {
                        "configuration": app.get("configuration", {}),
                        "template": rollback_template,
                    },
                }
                self._request_json(
                    "PATCH",
                    f"https://management.azure.com{app['resource_id']}?api-version=2024-03-01",
                    "https://management.azure.com/",
                    body,
                    poll_async=False,
                    retry_safe=True,
                    stage=f"ARM rollback Container App {app.get('name', '<unknown>')}",
                )
                if not self._wait_for_rollback_state(app, rollback_template):
                    failures.append(f"{app['name']} revision/traffic verification failed")
                else:
                    restored.append(f"containerapp:{app['name']}")
            except Exception as exc:
                failures.append(f"{app.get('name')} rollback failed: {exc}")
        for variable, value in (
            inventory.get("azd", {}).get("service_images", {}) or {}
        ).items():
            if not value:
                continue
            completed = _run_command(
                ["azd", "env", "set", variable, value],
                operation=f"restore azd environment variable {variable}",
                cwd=_PYTHON_ROOT.parent,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode:
                failures.append(f"{variable} azd environment restore failed")
            else:
                self.env[variable] = value
        if failures:
            raise VerificationError("deployment rollback failed: " + "; ".join(failures))
        return {"status": "PASS", "restored": restored, "verified": True}

    def _wait_for_rollback_state(
        self,
        app: dict[str, Any],
        expected_template: dict[str, Any] | None = None,
    ) -> bool:
        deadline = time.monotonic() + self.args.timeout_seconds
        expected = copy.deepcopy(expected_template or app.get("template", {}))
        expected.pop("revisionSuffix", None)
        while time.monotonic() <= deadline:
            observed = self._request_json(
                "GET",
                f"https://management.azure.com{app['resource_id']}?api-version=2024-03-01",
                "https://management.azure.com/",
            )
            properties = (observed or {}).get("properties", {})
            observed_template = copy.deepcopy(properties.get("template", {}))
            observed_template.pop("revisionSuffix", None)
            template_matches = sha256_json(observed_template) == sha256_json(expected)
            traffic_matches = sha256_json(
                properties.get("configuration", {}).get("ingress", {}).get("traffic", [])
            ) == sha256_json(app.get("traffic", []))
            state = str(properties.get("provisioningState", "")).lower()
            if template_matches and traffic_matches and state in {"", "succeeded"}:
                return True
            if state in {"failed", "cancelled"}:
                return False
            time.sleep(self.args.poll_interval)
        return False

    def recompute_in_process(self) -> dict[str, Any]:
        return self.optimization_insights.recompute_controlled_demo4(self.database)

    def run_fabric_controller(self) -> dict[str, Any]:
        return self._external_evidence("CONTROLLED_DEMO_FABRIC_CONTROLLER_COMMAND")

    def verify_hosted_api(self) -> dict[str, Any]:
        return verify_hosted_session(self.args.base_url)

    def restore(self, path: Path) -> dict[str, Any]:
        return self.backup_store.restore(path)


class LocalSimulationRuntime:
    """Pure source-controlled evidence used by local-simulation mode."""

    def __init__(self, args: argparse.Namespace):
        self.args = args

    def identity_preflight(self) -> dict[str, Any]:
        return {"status": "PASS", "provider": "local-simulation"}

    def direct_snapshot(self) -> dict[str, Any]:
        tenants = {}
        for tenant in TENANTS:
            tenants[tenant] = build_tenant_manifest(
                tenant,
                fixture_version=self.args.fixture,
                anchor=self.args.anchor,
                count=self.args.count,
            )
            tenants[tenant].update({name: [] for name in DERIVED_CONTAINERS})
        funnel = {
            tenant: {
                "stages": EXPECTED_FUNNEL,
                "conversion_rate": 29.2,
                "largest_cause": {"name": "city_friction", "count": 52},
            }
            for tenant in TENANTS
        }
        return {
            "tenants": tenants,
            "funnel": funnel,
            "policy_statuses": {
                tenant: "reverted" for tenant in TENANTS
            },
            "protected_unchanged": True,
        }

    def verify_hosted_api(self) -> dict[str, Any]:
        return verify_hosted_session(self.args.base_url)

    def git_head(self) -> str:
        completed = _run_command(
            ["git", "rev-parse", "HEAD"],
            operation="read Git HEAD",
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()


def _backup_manifest_path(value: str | None, mode: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if mode == "restore" and path.is_dir():
        candidates = sorted(path.glob("*.json"))
        if not candidates:
            raise VerificationError(f"no backup manifest found in {path}")
        return candidates[-1]
    if path.suffix.lower() == ".json":
        return path
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return path / f"controlled-demo4-backup-{stamp}.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, default="manifest-only")
    parser.add_argument("--recompute", choices=RECOMPUTE_CHOICES, default="none")
    parser.add_argument("--fixture", default=FIXTURE_VERSION)
    parser.add_argument("--burst", default=BURST_VERSION)
    parser.add_argument("--anchor", default=DEFAULT_ANCHOR)
    parser.add_argument("--burst-anchor", default=BURST_ANCHOR)
    parser.add_argument("--count", type=int, default=TURN_COUNT)
    parser.add_argument("--window-minutes", type=int, default=WINDOW_MINUTES)
    parser.add_argument("--base-url")
    parser.add_argument("--backup-dir")
    parser.add_argument("--cosmos-endpoint")
    parser.add_argument("--database")
    parser.add_argument("--azure-tenant")
    parser.add_argument("--subscription")
    parser.add_argument("--resource-group")
    parser.add_argument(
        "--deployment-transport",
        choices=DEPLOYMENT_TRANSPORTS,
        default="auto",
        help=(
            "auto uses azd only when azd/Azure CLI authentication matches the intended "
            "tenant/subscription; otherwise it builds, pushes, and patches existing apps directly"
        ),
    )
    parser.add_argument(
        "--pip-index-url",
        help=(
            "HTTPS Python package index for direct Docker builds. Precedence: this option, "
            "PIP_INDEX_URL, host pip global.index-url, then https://pypi.org/simple. "
            "Userinfo is rejected and query values are redacted from output."
        ),
    )
    parser.add_argument(
        "--npm-registry-url",
        help=(
            "HTTPS npm registry for direct Docker builds. Precedence: this option, "
            "NPM_CONFIG_REGISTRY, host npm registry, then https://registry.npmjs.org/. "
            "Userinfo is rejected and query values are redacted from output."
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--starting-git-sha", default="b62e7b0868094b209f9ee48c84b8ed68dcd8a440")
    parser.add_argument("--check-manifest-only", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.check_manifest_only:
        if args.mode not in {"manifest-only", "baseline-live"}:
            raise SystemExit("--check-manifest-only conflicts with the selected --mode")
        args.mode = "manifest-only"
    backup_path = _backup_manifest_path(args.backup_dir, args.mode)
    config = VerifierConfig(
        mode=args.mode,
        recompute=args.recompute,
        backup_path=backup_path,
        timeout_seconds=args.timeout_seconds,
        starting_git_sha=args.starting_git_sha,
        arguments={
            "fixture": args.fixture,
            "burst": args.burst,
            "anchor": args.anchor,
            "burst_anchor": args.burst_anchor,
            "count": args.count,
            "window_minutes": args.window_minutes,
            "base_url": args.base_url,
        },
    )
    try:
        if args.mode == "manifest-only":
            class ManifestRuntime:
                def git_head(self) -> str:
                    completed = _run_command(
                        ["git", "rev-parse", "HEAD"],
                        operation="read Git HEAD",
                        cwd=_REPO_ROOT,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    return completed.stdout.strip()

            runtime: Any = ManifestRuntime()
        elif args.mode == "local-simulation":
            runtime = LocalSimulationRuntime(args)
        else:
            runtime = LiveRuntime(args)
        result = ControlledDemo4Verifier(runtime, config).run()
        if args.base_url and args.mode == "local-simulation":
            result["hosted_api"] = runtime.verify_hosted_api()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {
            "status": "FAIL",
            "mode": args.mode,
            "error": _redact_sensitive_text(
                str(exc),
                (
                    {
                        args.pip_index_url: safe_pip_index_url(args.pip_index_url)
                    }
                    if args.pip_index_url
                    else None
                ),
            ),
            "restore_command": (
                f"python data\\verify_controlled_demo4.py --mode restore --backup-dir \"{backup_path}\""
                if backup_path
                else None
            ),
        }
        print(json.dumps(failure, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
