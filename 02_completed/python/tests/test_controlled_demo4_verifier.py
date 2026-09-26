from __future__ import annotations

import base64
import copy
import http.client
import io
import json
import shutil
import subprocess
import urllib.error
import uuid
from argparse import Namespace
from collections import Counter
from pathlib import Path

import pytest

import data.verify_controlled_demo4 as verifier_cli
from src.app.services.controlled_demo4 import (
    CANONICAL_MINUTE_PROFILE,
    COHORT_CONTAINERS,
    DERIVED_CONTAINERS,
    EXPECTED_FUNNEL,
    TENANTS,
    build_tenant_manifest,
)
from src.app.services.controlled_demo4_verifier import (
    FORBIDDEN_BASELINE_OPERATIONS,
    MIRROR_TABLES,
    AzurePowerShellTokenCredential,
    ChainedTokenProvider,
    ControlledDemo4Verifier,
    CosmosBackupStore,
    IdentityIntent,
    IdentityPreflight,
    VerificationError,
    VerifierConfig,
    poll_mirror_convergence,
    sha256_json,
    validate_backup_manifest,
    validate_baseline_snapshot,
    verify_hosted_session,
    write_durable_json,
)
from data.verify_controlled_demo4 import (
    LiveRuntime,
    discover_npm_registry_url,
    discover_pip_index_url,
    safe_pip_index_url,
    select_deployment_transport,
    update_template_image,
    validate_npm_registry_url,
    validate_pip_index_url,
)

START_SHA = "b62e7b0868094b209f9ee48c84b8ed68dcd8a440"


class _FakeHttpResponse:
    def __init__(self, payload=None, *, status=200, headers=None):
        self.status = status
        self.headers = headers or {}
        self._body = json.dumps(payload or {}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._body


def _http_runtime():
    runtime = object.__new__(LiveRuntime)
    runtime.args = Namespace(timeout_seconds=30)
    runtime.token_provider = type(
        "TokenProvider",
        (),
        {"get_token": lambda self, resource: "test-token"},
    )()
    return runtime


@pytest.fixture
def work_dir():
    path = Path(__file__).resolve().parents[3] / ".local" / "brief-f-tests" / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _baseline_snapshot():
    tenants = {}
    for tenant in TENANTS:
        tenants[tenant] = build_tenant_manifest(tenant)
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


class FakeRuntime:
    def __init__(
        self,
        *,
        preflight_error=None,
        head=START_SHA,
        failures=None,
        deployment_failure_mutated=False,
    ):
        self.calls = []
        self.preflight_error = preflight_error
        self.head = head
        self.failures = failures or {}
        self._deployment_mutated = False
        self.deployment_failure_mutated = deployment_failure_mutated

    def _record(self, name, result=None):
        self.calls.append(name)
        if name in self.failures:
            raise VerificationError(self.failures[name])
        return result or {"status": "PASS"}

    def identity_preflight(self):
        self.calls.append("identity_preflight")
        if self.preflight_error:
            raise self.preflight_error
        return {"status": "PASS"}

    def capture_backup(self, path, arguments):
        return self._record("backup", {"status": "PASS", "path": str(path)})

    def capture_deployment_inventory(self, backup_path):
        return self._record(
            "deployment_inventory",
            {
                "azd": {"flags": {"DEPLOY_ANALYTICS": "true"}, "frontend_uri": "https://example"},
                "container_apps": [{"revision": "api--before", "traffic": [{"weight": 100}]}],
                "fabric": {"completed_notebook": True, "pipeline": "RefreshAllDemoTenants"},
            },
        )

    def deploy_existing_topology(self):
        self.calls.append("deploy_existing_topology")
        if "deploy_existing_topology" in self.failures:
            self._deployment_mutated = self.deployment_failure_mutated
            raise VerificationError(self.failures["deploy_existing_topology"])
        self._deployment_mutated = True
        return {"status": "PASS"}

    def deployment_mutated(self):
        return self._deployment_mutated

    def rollback_deployment(self, inventory):
        return self._record(
            "rollback_deployment",
            {"status": "PASS", "verified": True},
        )

    def reset(self):
        return self._record("reset")

    def direct_snapshot(self):
        self.calls.append("direct_snapshot")
        return _baseline_snapshot()

    def poll_mirror(self, expectation, timeout_seconds):
        return self._record(
            "mirror_poll",
            {"status": "PASS", "mounted_tables": list(MIRROR_TABLES)},
        )

    def verify_power_bi_baseline(self, tenants):
        return self._record(
            "power_bi_baseline",
            {"status": "PASS", "tenants": list(tenants), "derived_visuals": "empty"},
        )

    def recompute_in_process(self):
        return self._record("recompute_in_process")

    def run_fabric_controller(self):
        return self._record(
            "fabric_controller",
            {"order": ["analytics", "marvel"], "shared_written_once": True},
        )

    def verify_hosted_api(self):
        return self._record("hosted_api")

    def restore(self, path):
        return self._record("restore", {"status": "PASS", "path": str(path)})

    def git_head(self):
        self.calls.append("git_head")
        return self.head


def _config(mode, tmp_path, recompute="none", head=START_SHA):
    return VerifierConfig(
        mode=mode,
        recompute=recompute,
        backup_path=tmp_path / "backup.json",
        starting_git_sha=head,
    )


def test_baseline_live_structurally_excludes_apply_traffic_recompute_controller_and_freshen(work_dir):
    runtime = FakeRuntime()
    result = ControlledDemo4Verifier(runtime, _config("baseline-live", work_dir)).run()

    assert result["status"] == "PASS"
    assert runtime.calls[:2] == ["identity_preflight", "backup"]
    assert not FORBIDDEN_BASELINE_OPERATIONS.intersection(runtime.calls)
    assert runtime.calls == [
        "identity_preflight",
        "backup",
        "deployment_inventory",
        "deploy_existing_topology",
        "reset",
        "direct_snapshot",
        "mirror_poll",
        "power_bi_baseline",
        "git_head",
    ]


def test_identity_preflight_failure_occurs_before_backup_deploy_or_reset(work_dir):
    runtime = FakeRuntime(preflight_error=VerificationError("wrong tenant"))
    with pytest.raises(VerificationError, match="wrong tenant"):
        ControlledDemo4Verifier(runtime, _config("baseline-live", work_dir)).run()
    assert runtime.calls == ["identity_preflight"]


@pytest.mark.parametrize(
    "failure_point",
    ["reset", "mirror_poll", "power_bi_baseline"],
)
def test_baseline_live_failure_after_mutation_automatically_rolls_back(
    work_dir, failure_point
):
    runtime = FakeRuntime(failures={failure_point: f"{failure_point} failed"})
    with pytest.raises(
        VerificationError, match=r"baseline-live failed: .*rollback_status=PASS"
    ):
        ControlledDemo4Verifier(runtime, _config("baseline-live", work_dir)).run()
    assert "restore" in runtime.calls
    assert "rollback_deployment" in runtime.calls


def test_deployment_failure_before_mutation_does_not_run_any_rollback(work_dir):
    runtime = FakeRuntime(
        failures={"deploy_existing_topology": "build failed before mutation"}
    )
    with pytest.raises(VerificationError, match="build failed before mutation"):
        ControlledDemo4Verifier(runtime, _config("baseline-live", work_dir)).run()
    assert "restore" not in runtime.calls
    assert "rollback_deployment" not in runtime.calls


def test_deployment_failure_after_first_arm_patch_rolls_back_deployment_only(work_dir):
    runtime = FakeRuntime(
        failures={"deploy_existing_topology": "second patch failed"},
        deployment_failure_mutated=True,
    )
    with pytest.raises(VerificationError, match="rollback_status=PASS"):
        ControlledDemo4Verifier(runtime, _config("baseline-live", work_dir)).run()
    assert "restore" not in runtime.calls
    assert "rollback_deployment" in runtime.calls


def test_baseline_live_reports_rollback_failure_with_original_error(work_dir):
    runtime = FakeRuntime(
        failures={"reset": "reset exploded", "rollback_deployment": "traffic restore failed"}
    )
    with pytest.raises(VerificationError) as caught:
        ControlledDemo4Verifier(runtime, _config("baseline-live", work_dir)).run()
    message = str(caught.value)
    assert "reset exploded" in message
    assert "rollback_status=FAIL" in message
    assert "traffic restore failed" in message


def test_baseline_live_git_failure_is_rolled_back(work_dir):
    runtime = FakeRuntime(head="different")
    with pytest.raises(VerificationError, match="rollback_status=PASS"):
        ControlledDemo4Verifier(runtime, _config("baseline-live", work_dir)).run()
    assert "restore" in runtime.calls
    assert "rollback_deployment" in runtime.calls


def test_baseline_live_does_not_rollback_before_mutation(work_dir):
    runtime = FakeRuntime(failures={"deployment_inventory": "inventory failed"})
    with pytest.raises(VerificationError, match="inventory failed"):
        ControlledDemo4Verifier(runtime, _config("baseline-live", work_dir)).run()
    assert "restore" not in runtime.calls
    assert "rollback_deployment" not in runtime.calls


@pytest.mark.parametrize(
    ("requested", "authenticated", "tenant", "subscription", "expected"),
    [
        ("auto", False, "", "", "direct"),
        ("auto", True, "tenant-a", "sub-a", "azd"),
        ("auto", True, "wrong", "sub-a", "direct"),
        ("direct", True, "tenant-a", "sub-a", "direct"),
    ],
)
def test_deployment_transport_selection(
    requested, authenticated, tenant, subscription, expected
):
    assert (
        select_deployment_transport(
            requested,
            azd_authenticated=authenticated,
            cli_tenant=tenant,
            cli_subscription=subscription,
            intended_tenant="tenant-a",
            intended_subscription="sub-a",
        )
        == expected
    )


def test_explicit_azd_transport_fails_closed_on_identity_mismatch():
    with pytest.raises(VerificationError, match="does not match"):
        select_deployment_transport(
            "azd",
            azd_authenticated=True,
            cli_tenant="other",
            cli_subscription="sub-a",
            intended_tenant="tenant-a",
            intended_subscription="sub-a",
        )


def test_direct_transport_does_not_probe_missing_azd(monkeypatch):
    runtime = object.__new__(LiveRuntime)
    runtime.args = Namespace(deployment_transport="direct")
    runtime.tenant_id = "tenant-a"
    runtime.subscription_id = "sub-a"
    monkeypatch.setattr(
        verifier_cli.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("direct transport must not run auth commands"),
    )

    assert runtime._deployment_transport() == "direct"


def test_auto_transport_falls_back_to_direct_when_azd_is_missing(monkeypatch):
    runtime = object.__new__(LiveRuntime)
    runtime.args = Namespace(deployment_transport="auto")
    runtime.tenant_id = "tenant-a"
    runtime.subscription_id = "sub-a"
    monkeypatch.setattr(verifier_cli.shutil, "which", lambda executable: None)

    assert runtime._deployment_transport() == "direct"


def test_pip_index_discovery_prefers_explicit_then_environment():
    reader = lambda: pytest.fail("pip config must not be read")
    assert discover_pip_index_url(
        "https://explicit.example/simple",
        environ={"PIP_INDEX_URL": "https://environment.example/simple"},
        pip_config_reader=reader,
    ) == ("https://explicit.example/simple", "command-line")
    assert discover_pip_index_url(
        None,
        environ={"PIP_INDEX_URL": "https://environment.example/simple"},
        pip_config_reader=reader,
    ) == ("https://environment.example/simple", "environment")


def test_pip_index_discovery_uses_safe_host_config_and_defaults():
    configured = lambda: subprocess.CompletedProcess(
        [], 0, stdout="https://packagefeedproxy.microsoft.io/pypi/simple/\n", stderr=""
    )
    missing = lambda: subprocess.CompletedProcess([], 1, stdout="", stderr="")
    assert discover_pip_index_url(
        None, environ={}, pip_config_reader=configured
    ) == (
        "https://packagefeedproxy.microsoft.io/pypi/simple/",
        "host-pip-config",
    )
    assert discover_pip_index_url(
        None, environ={}, pip_config_reader=missing
    ) == ("https://pypi.org/simple", "default")


@pytest.mark.parametrize(
    "value",
    [
        "http://mirror.example/simple",
        "https://user:password@mirror.example/simple",
        "https://token@mirror.example/simple",
    ],
)
def test_pip_index_rejects_non_https_and_credential_bearing_urls(value):
    with pytest.raises(VerificationError):
        validate_pip_index_url(value)


def test_pip_index_safe_display_redacts_query_and_fragment():
    assert safe_pip_index_url(
        "https://mirror.example/simple?token=secret&channel=private#fragment"
    ) == "https://mirror.example/simple?channel=<redacted>&token=<redacted>"


def test_npm_registry_discovery_prefers_host_config():
    configured = lambda: subprocess.CompletedProcess(
        [], 0, stdout="https://packagefeedproxy.microsoft.io/npm/\n", stderr=""
    )
    assert discover_npm_registry_url(
        None, environ={}, npm_config_reader=configured
    ) == ("https://packagefeedproxy.microsoft.io/npm/", "host-npm-config")


@pytest.mark.parametrize(
    "value",
    [
        "http://registry.example/",
        "******registry.example/",
        "https://token@registry.example/",
    ],
)
def test_npm_registry_rejects_non_https_and_credential_bearing_urls(value):
    with pytest.raises(VerificationError):
        validate_npm_registry_url(value)


def test_safe_get_retries_connection_reset_with_capped_backoff(monkeypatch):
    runtime = _http_runtime()
    calls = []
    responses = [
        urllib.error.URLError(ConnectionResetError(10054, "connection reset")),
        _FakeHttpResponse({"status": "ok"}),
    ]

    def urlopen(request, timeout):
        calls.append(request.full_url)
        response = responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    sleeps = []
    monkeypatch.setattr(verifier_cli.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(verifier_cli.time, "sleep", sleeps.append)

    result = runtime._request_json(
        "GET",
        "https://management.azure.com/subscriptions/s?api-version=1&sig=secret",
        "https://management.azure.com/",
    )

    assert result == {"status": "ok"}
    assert len(calls) == 2
    assert sleeps == [0.5]


def test_transient_http_honors_retry_after_with_cap(monkeypatch):
    runtime = _http_runtime()
    error = urllib.error.HTTPError(
        "https://api.fabric.microsoft.com/v1/workspaces/w",
        429,
        "throttled",
        {"Retry-After": "30"},
        io.BytesIO(b"secret response must not be surfaced"),
    )
    responses = [error, _FakeHttpResponse({"value": []})]
    sleeps = []

    def urlopen(request, timeout):
        response = responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(verifier_cli.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(verifier_cli.time, "sleep", sleeps.append)

    assert runtime._request_json(
        "GET",
        "https://api.fabric.microsoft.com/v1/workspaces/w",
        "https://api.fabric.microsoft.com/",
    ) == {"value": []}
    assert sleeps == [8.0]


def test_nontransient_4xx_is_not_retried_and_error_redacts_query(monkeypatch):
    runtime = _http_runtime()
    calls = {"count": 0}

    def urlopen(request, timeout):
        calls["count"] += 1
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "bad request",
            {},
            io.BytesIO(b'{"access_token":"must-not-leak"}'),
        )

    monkeypatch.setattr(verifier_cli.urllib.request, "urlopen", urlopen)

    with pytest.raises(VerificationError) as caught:
        runtime._request_json(
            "GET",
            "https://api.powerbi.com/v1.0/myorg/reports/r?access_token=secret",
            "https://analysis.windows.net/powerbi/api",
        )

    message = str(caught.value)
    assert calls["count"] == 1
    assert "Power BI" in message
    assert "HTTP 400" in message
    assert "access_token=<redacted>" in message
    assert "secret" not in message
    assert "must-not-leak" not in message


def test_unsafe_post_does_not_retry_unknown_outcome(monkeypatch):
    runtime = _http_runtime()
    calls = {"count": 0}

    def urlopen(request, timeout):
        calls["count"] += 1
        raise urllib.error.URLError(
            http.client.RemoteDisconnected("remote disconnected")
        )

    monkeypatch.setattr(verifier_cli.urllib.request, "urlopen", urlopen)

    with pytest.raises(VerificationError, match="after 1 attempt"):
        runtime._request_json(
            "POST",
            "https://api.fabric.microsoft.com/v1/workspaces/w/items",
            "https://api.fabric.microsoft.com/",
            {"displayName": "would-be-mutation"},
        )
    assert calls["count"] == 1


def test_lro_poll_retries_remote_disconnect_and_preserves_completion(monkeypatch):
    runtime = _http_runtime()
    responses = [
        _FakeHttpResponse(
            {"accepted": True},
            status=202,
            headers={"Operation-Location": "https://management.azure.com/operations/o"},
        ),
        http.client.RemoteDisconnected("remote disconnected"),
        _FakeHttpResponse({"status": "Succeeded"}),
    ]
    calls = []

    def urlopen(request, timeout):
        calls.append((request.get_method(), request.full_url))
        response = responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(verifier_cli.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(verifier_cli.time, "sleep", lambda seconds: None)

    result = runtime._request_json(
        "PATCH",
        "https://management.azure.com/resource?api-version=1",
        "https://management.azure.com/",
        {"properties": {"value": "same-on-retry"}},
        retry_safe=True,
    )

    assert result == {"status": "Succeeded"}
    assert calls == [
        ("PATCH", "https://management.azure.com/resource?api-version=1"),
        ("GET", "https://management.azure.com/operations/o"),
        ("GET", "https://management.azure.com/operations/o"),
    ]


def test_acr_token_exchanges_retry_connection_reset(monkeypatch):
    runtime = object.__new__(LiveRuntime)
    runtime.env = {
        "AZURE_CONTAINER_REGISTRY_ENDPOINT": "registry.azurecr.io",
        "AZURE_CONTAINER_REGISTRY_NAME": "registry",
    }
    runtime.tenant_id = "tenant"
    runtime.token_provider = type(
        "TokenProvider",
        (),
        {"get_token": lambda self, resource: "arm-token"},
    )()
    responses = [
        urllib.error.URLError(ConnectionResetError(10054, "connection reset")),
        _FakeHttpResponse({"refresh_token": "refresh-secret"}),
        _FakeHttpResponse({"access_token": "access-secret"}),
    ]
    calls = []

    def urlopen(request, timeout):
        calls.append(request.full_url)
        response = responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(verifier_cli.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(verifier_cli.time, "sleep", lambda seconds: None)

    assert runtime._acr_access_token(["api"]) == (
        "registry.azurecr.io",
        "access-secret",
    )
    assert calls.count("https://registry.azurecr.io/oauth2/exchange") == 2
    assert calls.count("https://registry.azurecr.io/oauth2/token") == 1


def test_docker_missing_executable_is_wrapped_with_operation_and_path(monkeypatch):
    monkeypatch.setattr(verifier_cli.shutil, "which", lambda executable: None)

    with pytest.raises(VerificationError) as caught:
        LiveRuntime._run_docker(
            ["docker", "info"],
            operation="check Docker daemon availability",
        )

    message = str(caught.value)
    assert "check Docker daemon availability" in message
    assert "executable not found: 'docker'" in message
    assert str(verifier_cli._PYTHON_ROOT.parent) in message


def test_stage_analytics_portal_reports_missing_source(monkeypatch, work_dir):
    repo_root = work_dir / "repo"
    python_root = repo_root / "02_completed" / "python"
    python_root.mkdir(parents=True)
    monkeypatch.setattr(verifier_cli, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(verifier_cli, "_PYTHON_ROOT", python_root)

    with pytest.raises(VerificationError) as caught:
        LiveRuntime._stage_analytics_portal()

    message = str(caught.value)
    assert "stage Analytics Portal" in message
    assert str(repo_root / "analytics" / "dashboard" / "index.html") in message
    assert str(repo_root / "02_completed" / "analytics-portal" / "index.html") in message


def test_stage_analytics_portal_uses_dashboard_source(monkeypatch, work_dir):
    repo_root = work_dir / "repo"
    python_root = repo_root / "02_completed" / "python"
    source = repo_root / "analytics" / "dashboard" / "index.html"
    source.parent.mkdir(parents=True)
    python_root.mkdir(parents=True)
    source.write_text("portal", encoding="utf-8")
    monkeypatch.setattr(verifier_cli, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(verifier_cli, "_PYTHON_ROOT", python_root)

    LiveRuntime._stage_analytics_portal()

    destination = repo_root / "02_completed" / "analytics-portal" / "index.html"
    assert destination.read_text(encoding="utf-8") == "portal"


def test_template_update_changes_exactly_one_image_field():
    template = {
        "revisionSuffix": "before",
        "scale": {"minReplicas": 1},
        "containers": [
            {
                "name": "api",
                "image": "registry.example/api:old",
                "env": [{"name": "SETTING", "value": "unchanged"}],
            },
            {"name": "sidecar", "image": "registry.example/sidecar:fixed"},
        ],
    }
    updated = update_template_image(
        template, "registry.example/api:old", "registry.example/api:receipt"
    )
    assert template["containers"][0]["image"] == "registry.example/api:old"
    assert updated["containers"][0]["image"] == "registry.example/api:receipt"
    assert updated["containers"][0]["env"] == template["containers"][0]["env"]
    assert updated["containers"][1] == template["containers"][1]
    assert updated["revisionSuffix"] == template["revisionSuffix"]
    assert updated["scale"] == template["scale"]


def test_direct_arm_patch_preserves_configuration_and_changes_only_service_image(
    monkeypatch,
):
    runtime = object.__new__(LiveRuntime)
    runtime._deployment_mutated = False
    current_template = {
        "revisionSuffix": "before",
        "containers": [
            {
                "name": "api",
                "image": "registry.example/api:old",
                "env": [{"name": "A", "value": "B"}],
            }
        ],
        "scale": {"minReplicas": 1},
    }
    configuration = {
        "activeRevisionsMode": "Single",
        "ingress": {"traffic": [{"latestRevision": True, "weight": 100}]},
        "secrets": [{"name": "kept"}],
    }
    app = {
        "name": "api-app",
        "resource_id": "/subscriptions/s/resourceGroups/r/providers/Microsoft.App/containerApps/api",
        "template": copy.deepcopy(current_template),
        "images": ["registry.example/api:old"],
    }
    runtime._deployment_inventory = {"container_apps": [app]}
    requests = []

    def request_json(method, url, resource, payload=None, **kwargs):
        requests.append((method, payload, kwargs))
        if method == "GET":
            return {
                "location": "westus",
                "properties": {
                    "configuration": copy.deepcopy(configuration),
                    "template": copy.deepcopy(current_template),
                },
            }
        return {}

    monkeypatch.setattr(runtime, "_request_json", request_json)
    monkeypatch.setattr(
        runtime,
        "_wait_for_container_app",
        lambda resource_id, template, image: {
            "latest_revision": "api--receipt",
            "revision_health": "Healthy",
            "traffic": configuration["ingress"]["traffic"],
            "image": image,
        },
    )
    services = {
        "api": {
            "current_image": "registry.example/api:old",
            "new_image": "registry.example/api:receipt",
            "digest": f"sha256:{1:064x}",
        }
    }
    result = runtime._update_existing_container_apps(services)
    patch = next(payload for method, payload, _ in requests if method == "PATCH")
    assert patch["location"] == "westus"
    assert patch["properties"]["configuration"] == configuration
    assert patch["properties"]["template"]["revisionSuffix"] == "receipt"
    assert patch["properties"]["template"]["scale"] == {"minReplicas": 1}
    assert (
        patch["properties"]["template"]["containers"][0]["image"]
        == "registry.example/api:receipt"
    )
    assert patch["properties"]["template"]["containers"][0]["env"] == [
        {"name": "A", "value": "B"}
    ]
    assert result[0]["latest_revision"] == "api--receipt"
    assert runtime.deployment_mutated() is True


def test_direct_arm_patch_shortens_revision_suffix_to_platform_limit(monkeypatch):
    runtime = object.__new__(LiveRuntime)
    runtime._deployment_mutated = False
    app_name = "ca-api-f2tx5x7js4bwi"
    current_template = {
        "revisionSuffix": "before",
        "containers": [{"name": "api", "image": "registry.example/api:old"}],
    }
    app = {
        "name": app_name,
        "resource_id": "/subscriptions/s/resourceGroups/r/providers/Microsoft.App/containerApps/api",
        "template": copy.deepcopy(current_template),
        "images": ["registry.example/api:old"],
    }
    runtime._deployment_inventory = {"container_apps": [app]}
    patches = []

    def request_json(method, url, resource, payload=None, **kwargs):
        if method == "GET":
            return {
                "location": "westus",
                "properties": {
                    "configuration": {},
                    "template": copy.deepcopy(current_template),
                },
            }
        patches.append(payload)
        return {}

    monkeypatch.setattr(runtime, "_request_json", request_json)
    monkeypatch.setattr(runtime, "_wait_for_container_app", lambda *args: {})
    runtime._update_existing_container_apps(
        {
            "api": {
                "current_image": "registry.example/api:old",
                "new_image": (
                    "registry.example/api:"
                    "brief-f-b62e7b086809-935a5059bf61"
                ),
            }
        }
    )
    suffix = patches[0]["properties"]["template"]["revisionSuffix"]
    assert suffix.startswith("bf-")
    assert len(app_name) + 2 + len(suffix) <= 54


def test_direct_deployment_does_not_mutate_before_all_images_are_pushed(monkeypatch):
    runtime = object.__new__(LiveRuntime)
    runtime.args = Namespace(
        timeout_seconds=5,
        poll_interval=0,
        pip_index_url="https://mirror.example/simple?token=secret",
        npm_registry_url="https://npm.example/?token=secret",
    )
    runtime.env = {
        "AZURE_ENV_NAME": "test",
        "SERVICE_API_IMAGE_NAME": "registry.example/api:old",
        "SERVICE_MCP_SERVER_IMAGE_NAME": "registry.example/mcp:old",
        "SERVICE_FRONTEND_IMAGE_NAME": "registry.example/frontend:old",
    }
    runtime._deployment_inventory = {
        "capture_utc": "2026-09-24T16:00:00+00:00",
        "container_apps": [],
    }
    runtime._deployment_mutated = False
    monkeypatch.setattr(runtime, "git_head", lambda: START_SHA)
    monkeypatch.setattr(
        runtime, "_acr_access_token", lambda repositories: ("registry.example", "token")
    )
    monkeypatch.setattr(runtime, "_stage_analytics_portal", lambda: None)
    mutation_calls = []
    monkeypatch.setattr(
        runtime,
        "_update_existing_container_apps",
        lambda services: mutation_calls.append(services),
    )
    pushes = {"count": 0}
    builds = []

    def run_docker(command, operation=None, input_text=None, sensitive_values=None):
        if command[:2] == ["docker", "build"]:
            builds.append(command)
        if command[:2] == ["docker", "push"]:
            pushes["count"] += 1
            if pushes["count"] == 3:
                raise VerificationError("third push failed")
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=f"digest: sha256:{pushes['count']:064x}",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(runtime, "_run_docker", run_docker)
    with pytest.raises(VerificationError, match="third push failed"):
        runtime._deploy_container_apps_direct()
    assert pushes["count"] == 3
    assert len(builds) == 3
    for command in builds:
        build_args = [
            command[index + 1]
            for index, value in enumerate(command)
            if value == "--build-arg"
        ]
        assert build_args == [
            "PIP_INDEX_URL=https://mirror.example/simple?token=secret",
            "NPM_CONFIG_REGISTRY=https://npm.example/?token=secret",
        ]
        dockerfile = Path(command[command.index("--file") + 1])
        build_context = Path(command[-1])
        assert dockerfile.is_absolute()
        assert dockerfile.is_file()
        assert build_context == verifier_cli._PYTHON_ROOT.parent.resolve()
    assert mutation_calls == []
    assert runtime.deployment_mutated() is False


def test_docker_build_failure_redacts_pip_index_query(monkeypatch):
    runtime = object.__new__(LiveRuntime)
    raw = "https://mirror.example/simple?token=secret"
    monkeypatch.setattr(
        verifier_cli,
        "_run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout="", stderr=f"failed to fetch {raw}"
        ),
    )
    with pytest.raises(VerificationError) as caught:
        runtime._run_docker(
            ["docker", "build", "--build-arg", f"PIP_INDEX_URL={raw}", "."],
            sensitive_values={raw: safe_pip_index_url(raw)},
        )
    message = str(caught.value)
    assert "secret" not in message
    assert "token=<redacted>" in message


def test_rollback_poll_accepts_observed_matching_state_without_operation_url(
    monkeypatch,
):
    runtime = object.__new__(LiveRuntime)
    runtime.args = Namespace(timeout_seconds=5, poll_interval=0)
    app = {
        "resource_id": "/subscriptions/s/resourceGroups/r/providers/Microsoft.App/containerApps/api",
        "template": {"containers": [{"name": "api", "image": "old"}]},
        "traffic": [{"latestRevision": True, "weight": 100}],
    }
    monkeypatch.setattr(
        runtime,
        "_request_json",
        lambda *args, **kwargs: {
            "properties": {
                "provisioningState": "Succeeded",
                "template": copy.deepcopy(app["template"]),
                "configuration": {"ingress": {"traffic": copy.deepcopy(app["traffic"])}},
            }
        },
    )
    assert runtime._wait_for_rollback_state(app) is True


def test_restore_identity_preflight_occurs_before_restore_mutation(work_dir):
    runtime = FakeRuntime(preflight_error=VerificationError("wrong subscription"))
    with pytest.raises(VerificationError, match="wrong subscription"):
        ControlledDemo4Verifier(runtime, _config("restore", work_dir)).run()
    assert runtime.calls == ["identity_preflight"]


def test_post_traffic_default_is_read_only_and_never_apply_or_generate_traffic(work_dir):
    runtime = FakeRuntime()
    result = ControlledDemo4Verifier(runtime, _config("post-traffic", work_dir)).run()
    assert result["status"] == "PASS"
    assert runtime.calls == ["identity_preflight", "direct_snapshot", "git_head"]


@pytest.mark.parametrize(
    ("choice", "expected", "excluded"),
    [
        ("in-process", "recompute_in_process", "fabric_controller"),
        ("fabric", "fabric_controller", "recompute_in_process"),
    ],
)
def test_post_traffic_invokes_exactly_one_explicit_recompute_path(
    work_dir, choice, expected, excluded
):
    runtime = FakeRuntime()
    ControlledDemo4Verifier(
        runtime, _config("post-traffic", work_dir, recompute=choice)
    ).run()
    assert expected in runtime.calls
    assert excluded not in runtime.calls
    if choice == "fabric":
        assert runtime.calls.index("fabric_controller") < runtime.calls.index("mirror_poll")


def test_recompute_choice_is_rejected_outside_post_traffic(work_dir):
    with pytest.raises(VerificationError, match="only in post-traffic"):
        ControlledDemo4Verifier(
            FakeRuntime(), _config("baseline-live", work_dir, recompute="fabric")
        ).run()


def test_git_sha_preservation_is_a_blocking_hook(work_dir):
    with pytest.raises(VerificationError, match="Git SHA changed"):
        ControlledDemo4Verifier(
            FakeRuntime(head="different"), _config("post-traffic", work_dir)
        ).run()


def test_durable_backup_is_closed_reread_and_hash_verified(work_dir, monkeypatch):
    path = work_dir / "backup.json"
    original_replace = __import__("os").replace

    def corrupting_replace(source, destination):
        original_replace(source, destination)
        Path(destination).write_text('{"corrupted":true}\n', encoding="utf-8")

    monkeypatch.setattr("os.replace", corrupting_replace)
    with pytest.raises(VerificationError, match="reread integrity"):
        write_durable_json(path, {"safe": True})


def test_backup_manifest_integrity_rejects_tampering(work_dir):
    path = work_dir / "manifest.json"
    payload = {"schema_version": 2, "documents": {}}
    payload["integrity"] = {"manifest_sha256": sha256_json(payload)}
    write_durable_json(path, payload)
    assert validate_backup_manifest(path)["schema_version"] == 2
    altered = json.loads(path.read_text(encoding="utf-8"))
    altered["documents"]["unexpected"] = []
    path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(VerificationError, match="integrity failure"):
        validate_backup_manifest(path)


def test_exact_baseline_invariants_and_failure_diagnostics():
    snapshot = _baseline_snapshot()
    profile = tuple(
        count
        for _, count in sorted(
            Counter(
                row["timeStamp"][:16]
                for row in snapshot["tenants"]["analytics"]["OptimizationTurns"]
            ).items()
        )
    )
    assert profile == CANONICAL_MINUTE_PROFILE

    result = validate_baseline_snapshot(snapshot)
    assert result["status"] == "PASS"
    assert result["tenants"]["analytics"]["counts"]["OptimizationTurns"] == 200

    broken = copy.deepcopy(snapshot)
    turns = broken["tenants"]["analytics"]["OptimizationTurns"]
    turns[0]["timeStamp"] = turns[5]["timeStamp"]
    debug = {
        row["turnId"]: row
        for row in broken["tenants"]["analytics"]["Debug"]
    }
    debug[turns[0]["id"]]["timeStamp"] = turns[0]["timeStamp"]
    with pytest.raises(VerificationError, match="exact canonical non-flat profile"):
        validate_baseline_snapshot(broken)


def test_mirror_poll_uses_mounted_evidence_and_stale_deletion_not_fixed_sleep():
    observations = [
        {
            "mounted_tables": list(MIRROR_TABLES[:-1]),
            "exact_controlled_ids": False,
            "stale_derived_rows_deleted": False,
        },
        {
            "mounted_tables": list(MIRROR_TABLES),
            "exact_controlled_ids": True,
            "stale_derived_rows_deleted": True,
        },
    ]
    now = {"value": 0.0}

    def probe():
        return observations.pop(0)

    def clock():
        now["value"] += 0.1
        return now["value"]

    result = poll_mirror_convergence(
        probe,
        {},
        timeout_seconds=10,
        interval_seconds=0,
        clock=clock,
        sleep=lambda _: None,
    )
    assert result["status"] == "PASS"
    assert set(result["mounted_tables"]) == set(MIRROR_TABLES)


def test_mirror_timeout_diagnostics_name_missing_and_stale_evidence():
    now = {"value": 0.0}

    def clock():
        now["value"] += 1
        return now["value"]

    with pytest.raises(VerificationError, match="missing mounted tables=.*memories"):
        poll_mirror_convergence(
            lambda: {
                "mounted_tables": list(MIRROR_TABLES[:-1]),
                "exact_controlled_ids": False,
                "stale_derived_rows_deleted": False,
                "diagnostic": "mirror lagging",
            },
            {},
            timeout_seconds=1,
            interval_seconds=0,
            clock=clock,
            sleep=lambda _: None,
        )


def _jwt(tenant):
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(
        json.dumps({"tid": tenant, "aud": "test", "oid": "object"}).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{body}."


class TokenProvider:
    def __init__(self, tenant):
        self.tenant = tenant
        self.resources = []

    def get_token(self, resource):
        self.resources.append(resource)
        return _jwt(self.tenant)


def test_powershell_token_credential_adapts_resource_scope_to_access_token():
    provider = TokenProvider("tenant-a")
    credential = AzurePowerShellTokenCredential(provider)
    token = credential.get_token("https://cosmos.azure.com/.default")
    assert token.token == _jwt("tenant-a")
    assert provider.resources == ["https://cosmos.azure.com/"]
    assert token.expires_on > 0


def test_identity_preflight_reconciles_arm_cosmos_fabric_and_powerbi_claims():
    provider = TokenProvider("tenant-a")
    result = IdentityPreflight(
        IdentityIntent(
            tenant_id="tenant-a",
            subscription_id="sub-a",
            cosmos_account="account-a",
            cosmos_endpoint="https://account-a.documents.azure.com:443/",
        ),
        ChainedTokenProvider([provider]),
        lambda: {
            "tenant_id": "tenant-a",
            "subscription_id": "sub-a",
            "cosmos_account": "account-a",
            "cosmos_endpoint": "https://account-a.documents.azure.com:443/",
        },
    ).run()
    assert result["status"] == "PASS"
    assert len(provider.resources) == 4
    assert set(result["token_claims"]) == {"arm", "cosmos", "fabric", "power_bi"}


def test_identity_preflight_rejects_account_mismatch_before_tokens():
    provider = TokenProvider("tenant-a")
    with pytest.raises(VerificationError, match="account"):
        IdentityPreflight(
            IdentityIntent("tenant-a", "sub-a", "intended", "https://intended/"),
            provider,
            lambda: {
                "tenant_id": "tenant-a",
                "subscription_id": "sub-a",
                "cosmos_account": "other",
                "cosmos_endpoint": "https://other/",
            },
        ).run()
    assert provider.resources == []


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_hosted_api_reuses_returned_session_id_and_redacts_output():
    urls = []

    def request(req, timeout):
        urls.append(req.full_url)
        if len(urls) == 1:
            return FakeResponse({"sessionId": "server-returned-session"})
        assert "/sessions/server-returned-session/completion" in req.full_url
        return FakeResponse([])

    result = verify_hosted_session("https://example.test/api", request=request)
    assert result["session_id_reused"] is True
    assert "server-returned-session" not in result["completion_path"]
    assert "token" not in json.dumps(result).lower()


class FakeContainer:
    def __init__(self, name, rows, paths=None):
        self.name = name
        self.rows = copy.deepcopy(rows)
        self.paths = paths or ["/tenantId", "/userId", "/sessionId"]
        self.deletes = []
        self.upserts = []

    def read(self):
        return {"partitionKey": {"paths": self.paths}}

    def query_items(self, query, parameters=None, enable_cross_partition_query=False):
        tenants = next(
            (p["value"] for p in parameters or [] if p["name"] == "@tenants"),
            None,
        )
        if tenants is None:
            return copy.deepcopy(self.rows)
        include = "NOT ARRAY_CONTAINS" not in query
        return [
            copy.deepcopy(row)
            for row in self.rows
            if ((row.get("tenantId") in tenants) == include)
        ]

    def delete_item(self, item, partition_key):
        self.deletes.append((item, partition_key))
        self.rows = [row for row in self.rows if row["id"] != item]

    def upsert_item(self, document):
        self.upserts.append(copy.deepcopy(document))
        self.rows = [row for row in self.rows if row["id"] != document["id"]]
        self.rows.append(copy.deepcopy(document))
        return copy.deepcopy(document)


class FakeDatabase:
    def __init__(self):
        self.containers = {}
        for name in (*COHORT_CONTAINERS, *DERIVED_CONTAINERS):
            rows = []
            for tenant in TENANTS:
                rows.append(
                    {
                        "id": f"saved-{name}-{tenant}",
                        "tenantId": tenant,
                        "userId": f"user-{tenant}",
                        "sessionId": f"session-{tenant}",
                        "value": "saved",
                    }
                )
            rows.append(
                {
                    "id": f"protected-{name}",
                    "tenantId": "other",
                    "userId": "other",
                    "sessionId": "other",
                    "value": "protected",
                }
            )
            self.containers[name] = FakeContainer(name, rows)
        self.containers["OptimizationPolicies"] = FakeContainer(
            "OptimizationPolicies",
            [
                {
                    "id": f"{tenant}::model-selection",
                    "scenario": "model-selection",
                    "tenant_id": tenant,
                    "status": "active",
                    "params": {"enabled": True},
                    "audit": [],
                }
                for tenant in TENANTS
            ],
            ["/scenario"],
        )
        for name in ("Users", "Memories", "memories", "Checkpoints", "ApiEvents"):
            self.containers[name] = FakeContainer(
                name,
                [{"id": name, "tenantId": "other", "value": "protected"}],
                ["/tenantId"],
            )

    def get_container_client(self, name):
        return self.containers[name]


class FakePolicyService:
    def __init__(self, database):
        self.database = database
        self.calls = 0

    def restore_policy_snapshot(self, snapshot):
        self.calls += 1
        return self.database.containers["OptimizationPolicies"].upsert_item(snapshot)


def test_restore_is_bounded_and_uses_policy_lifecycle_service(work_dir):
    database = FakeDatabase()
    policies = FakePolicyService(database)
    store = CosmosBackupStore(
        database,
        endpoint="https://account.documents.azure.com:443/",
        database_name="TravelAssistant",
        policy_service=policies,
    )
    path = work_dir / "backup.json"
    store.capture(
        path,
        {
            "fixture": "controlled-demo4-v1",
            "burst": "controlled-demo4-after-v1",
            "anchor": "2026-09-24T12:00:00Z",
            "burst_anchor": "2026-09-24T13:00:00Z",
            "count": 200,
            "window_minutes": 20,
        },
    )
    owned_turn_id = validate_backup_manifest(path)["owned_ids"]["OptimizationTurns"][0]
    unrelated_before = {
        name: copy.deepcopy(container.rows[-1])
        for name, container in database.containers.items()
        if name in (*COHORT_CONTAINERS, *DERIVED_CONTAINERS)
    }
    database.containers["OptimizationTurns"].rows.append(
        {
            "id": owned_turn_id,
            "tenantId": "analytics",
            "userId": "controlled-demo4-analytics",
            "sessionId": "changed",
            "value": "verifier-owned",
        }
    )
    database.containers["OptimizationInsights"].rows.append(
        {
            "id": "unexpected-derived",
            "tenantId": "analytics",
            "userId": "analytics",
            "sessionId": "analytics",
            "value": "concurrent",
        }
    )

    with pytest.raises(VerificationError, match="restore conflict"):
        store.restore(path)

    assert policies.calls == 0
    for name, expected in unrelated_before.items():
        assert expected in database.containers[name].rows
    assert any(
        row["id"] == "unexpected-derived"
        for row in database.containers["OptimizationInsights"].rows
    )


def test_restore_deletes_only_manifest_owned_ids_and_restores_original_partitions(work_dir):
    database = FakeDatabase()
    policies = FakePolicyService(database)
    store = CosmosBackupStore(
        database,
        endpoint="https://account.documents.azure.com:443/",
        database_name="TravelAssistant",
        policy_service=policies,
    )
    path = work_dir / "backup.json"
    store.capture(path, {})
    manifest = validate_backup_manifest(path)
    owned_turn_id = manifest["owned_ids"]["OptimizationTurns"][0]
    database.containers["OptimizationTurns"].rows.append(
        {
            "id": owned_turn_id,
            "tenantId": "analytics",
            "userId": "controlled-demo4-analytics",
            "sessionId": "controlled-demo4-session",
            "value": "verifier-owned",
        }
    )

    result = store.restore(path)

    assert result["status"] == "PASS"
    assert policies.calls == 2
    assert any(item == owned_turn_id for item, _ in database.containers["OptimizationTurns"].deletes)
    restored = {
        row["id"]: row for row in database.containers["OptimizationTurns"].rows
    }
    assert restored["saved-OptimizationTurns-analytics"]["sessionId"] == "session-analytics"


def test_backup_tracks_operational_trips_as_protected_scope(work_dir):
    database = FakeDatabase()
    store = CosmosBackupStore(
        database,
        endpoint="https://account.documents.azure.com:443/",
        database_name="TravelAssistant",
        policy_service=FakePolicyService(database),
    )

    protected = store.protected_hashes()

    assert protected["Trips:analytics:operational"]["count"] == 1
    assert protected["Trips:marvel:operational"]["count"] == 1
