#!/usr/bin/env python3
"""Validate deployment hooks and optionally build all source Dockerfiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
COMPLETED = ROOT / "02_completed"
DOCKERFILES = {
    "api": COMPLETED / "Dockerfile.api",
    "frontend": COMPLETED / "Dockerfile.frontend",
    "mcp": COMPLETED / "Dockerfile.mcp",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_text(azure_text: str, docker_texts: dict[str, str]) -> None:
    if "reset_optimization_state.py" in azure_text:
        raise AssertionError("automatic reset hook remains in azure.yaml")
    required_in_order = [
        "prepackage:",
        "python data/seed_data.py",
        "python data/seed_configuration.py",
        "funnel_seed.py",
        "seed_gsi_trips.py",
        "postdeploy:",
    ]
    positions = [azure_text.find(token) for token in required_in_order]
    if any(position < 0 for position in positions):
        missing = [
            token for token, position in zip(required_in_order, positions) if position < 0
        ]
        raise AssertionError(f"required deployment hooks missing: {missing}")
    if positions != sorted(positions):
        raise AssertionError("deployment package/seed/postdeploy ordering changed")
    for service, dockerfile in (
        ("mcp-server", "Dockerfile.mcp"),
        ("api", "Dockerfile.api"),
        ("frontend", "Dockerfile.frontend"),
    ):
        block = re.search(
            rf"(?ms)^  {re.escape(service)}:\s+.*?(?=^  [a-zA-Z][^:\n]*:|^hooks:)",
            azure_text,
        )
        if not block or f"path: ./{dockerfile}" not in block.group(0):
            raise AssertionError(f"{service} is not wired to {dockerfile}")
        if "context: ." not in block.group(0):
            raise AssertionError(f"{service} does not build from repository source context")

    prohibited = [
        r"(?im)^\s*(docker|podman)\s+pull\b",
        r"(?im)^\s*az\s+acr\s+import\b",
        r"(?im)\bbuildx\s+imagetools\b",
        r"(?im)^\s*FROM\s+\S*\.azurecr\.io/",
        r"(?im)^\s*COPY\s+--from=\S*\.azurecr\.io/",
        r"(?im)\bdeployed[-_ ]image[-_ ]overlay\b",
        r"(?im)\bprebuilt[-_ ]image[-_ ]bypass\b",
    ]
    combined = azure_text + "\n" + "\n".join(docker_texts.values())
    for pattern in prohibited:
        if re.search(pattern, combined):
            raise AssertionError(f"prohibited deployed-image/overlay path: {pattern}")
    for name, content in docker_texts.items():
        if not re.search(r"(?m)^COPY\s+", content):
            raise AssertionError(f"{name} Dockerfile does not copy repository source")
        if not re.search(r"(?m)^FROM\s+(python|node|nginx)(?=[:\s])", content):
            raise AssertionError(f"{name} Dockerfile lacks an approved source base stage")


def validate_repository() -> None:
    azure_text = (COMPLETED / "azure.yaml").read_text(encoding="utf-8")
    docker_texts = {
        name: path.read_text(encoding="utf-8") for name, path in DOCKERFILES.items()
    }
    validate_text(azure_text, docker_texts)
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", *[str(p.relative_to(ROOT)) for p in DOCKERFILES.values()]],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if tracked.returncode:
        raise AssertionError("all source Dockerfiles must be tracked by git")


def safe_registry(value: str, label: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{label} must be an HTTPS URL without userinfo")
    return value.strip()


def configured_value(command: list[str], fallback: str) -> str:
    executable_command = list(command)
    if sys.platform == "win32" and Path(executable_command[0]).suffix == "":
        resolved = shutil.which(executable_command[0])
        if resolved:
            executable_command[0] = resolved
    result = subprocess.run(
        executable_command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else fallback


def configured_pip_index() -> str:
    direct = configured_value(
        [sys.executable, "-m", "pip", "config", "get", "global.index-url"], ""
    )
    if direct:
        return direct
    listing = configured_value(
        [sys.executable, "-m", "pip", "config", "list"], ""
    )
    match = re.search(r"(?m)index-url='([^']+)'", listing)
    return match.group(1) if match else "https://pypi.org/simple"


def build_all(
    evidence_dir: Path,
    *,
    pip_index_url: str | None = None,
    npm_registry_url: str | None = None,
) -> None:
    if not shutil.which("docker"):
        raise RuntimeError("docker executable is unavailable")
    probe = subprocess.run(
        ["docker", "info"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if probe.returncode:
        raise RuntimeError(
            "docker daemon is unavailable: "
            + probe.stderr.decode("utf-8", "replace").strip()
        )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    pip_index_url = safe_registry(
        pip_index_url
        or configured_pip_index(),
        "PIP index",
    )
    npm_registry_url = safe_registry(
        npm_registry_url
        or configured_value(
            ["npm", "config", "get", "registry"],
            "https://registry.npmjs.org/",
        ),
        "npm registry",
    )
    receipt_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    receipts = []
    for service, dockerfile in DOCKERFILES.items():
        tag = f"travel-workshop-brief-a-{service}:{receipt_id.lower()}"
        command = [
            "docker",
            "build",
            "--pull",
            "--no-cache",
            "--file",
            str(dockerfile.relative_to(ROOT)),
            "--tag",
            tag,
            "--label",
            f"org.opencontainers.image.revision={head}",
            "--label",
            f"travel.workshop.source-dockerfile-sha256={sha256(dockerfile)}",
            "--label",
            f"travel.workshop.build-receipt={receipt_id}",
        ]
        if service in {"api", "mcp"}:
            command.extend(["--build-arg", f"PIP_INDEX_URL={pip_index_url}"])
        if service == "frontend":
            command.extend(
                ["--build-arg", f"NPM_CONFIG_REGISTRY={npm_registry_url}"]
            )
        command.append(str(COMPLETED.relative_to(ROOT)))
        started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result = subprocess.run(command, cwd=ROOT, check=False)
        completed = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if result.returncode:
            raise SystemExit(result.returncode)
        image_id = subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
            cwd=ROOT,
        ).decode().strip()
        receipts.append(
            {
                "service": service,
                "command": command,
                "tag": tag,
                "image_id": image_id,
                "dockerfile": str(dockerfile.relative_to(ROOT)).replace("\\", "/"),
                "dockerfile_sha256": sha256(dockerfile),
                "head": head,
                "started_utc": started,
                "completed_utc": completed,
                "exit_code": result.returncode,
                "pushed": False,
            }
        )
    output = evidence_dir / "source-build-receipts.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "receipt_id": receipt_id,
                "source_build_only": True,
                "images": receipts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"source build receipts: {output.relative_to(ROOT)}")


def self_test() -> int:
    valid_azure = """
services:
  mcp-server:
    docker:
      path: ./Dockerfile.mcp
      context: .
  api:
    docker:
      path: ./Dockerfile.api
      context: .
  frontend:
    docker:
      path: ./Dockerfile.frontend
      context: .
hooks:
  prepackage:
    run: stage
  postprovision:
    run: |
      python data/seed_data.py
      python data/seed_configuration.py
      python ../../analytics/scripts/funnel_seed.py
      python data/seed_gsi_trips.py
  postdeploy:
    run: restart
"""
    docker = {
        "api": "FROM python:3.12-slim\nCOPY python/ ./python/\n",
        "frontend": "FROM node:20-alpine\nCOPY frontend/ ./\n",
        "mcp": "FROM python:3.12-slim\nCOPY mcp_server/ ./mcp_server/\n",
    }
    validate_text(valid_azure, docker)
    for bad in (
        valid_azure.replace(
            "python data/seed_gsi_trips.py",
            "python data/reset_optimization_state.py\n      python data/seed_gsi_trips.py",
        ),
        valid_azure + "\n  docker pull registry/image:tag\n",
    ):
        try:
            validate_text(bad, docker)
        except AssertionError:
            pass
        else:
            raise AssertionError("negative fixture was not rejected")
    service_refs = valid_azure + "\n# SERVICE_API_IMAGE_NAME may be updated by ARM deployment\n"
    validate_text(service_refs, docker)
    print("validate_deployment_source_builds self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-all", action="store_true")
    parser.add_argument(
        "--evidence-dir", default=".local/integration-evidence"
    )
    parser.add_argument("--pip-index-url")
    parser.add_argument("--npm-registry-url")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    validate_repository()
    print("deployment source-build static validation: PASS")
    if args.build_all:
        build_all(
            (ROOT / args.evidence_dir).resolve(),
            pip_index_url=args.pip_index_url,
            npm_registry_url=args.npm_registry_url,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
