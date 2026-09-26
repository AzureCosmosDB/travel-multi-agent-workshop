"""Fabric controller and mirror-convergence hook for the controlled Demo 4 verifier.

The command delegates evidence collection to explicit JSON-emitting commands so tests and
operators can inject the environment-specific Fabric REST/SQL implementation.  It never treats
elapsed time alone as convergence.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_ROOT = _REPO_ROOT / "02_completed" / "python"
sys.path.insert(0, str(_PYTHON_ROOT))

from src.app.services.controlled_demo4_verifier import (  # noqa: E402
    MIRROR_TABLES,
    VerificationError,
    poll_mirror_convergence,
)


def _redact(value):
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if any(marker in key.lower() for marker in ("token", "secret", "credential", "password", "api_key"))
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _command_json(command: str) -> dict:
    completed = subprocess.run(
        shlex.split(command),
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise VerificationError(
            completed.stderr.strip() or f"evidence command failed: {command}"
        )
    return _redact(json.loads(completed.stdout))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-pipeline", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--controller-command", default=os.environ.get("CONTROLLED_DEMO_FABRIC_CONTROLLER_COMMAND"))
    parser.add_argument("--mirror-probe-command", default=os.environ.get("CONTROLLED_DEMO_MIRROR_PROBE_COMMAND"))
    args = parser.parse_args()
    try:
        controller = None
        if args.run_pipeline:
            if not args.controller_command:
                raise VerificationError("--run-pipeline requires --controller-command")
            controller = _command_json(args.controller_command)
            if controller.get("order") != ["analytics", "marvel"]:
                raise VerificationError("Fabric controller evidence must prove Analytics then Marvel")
            if controller.get("shared_written_once") is not True:
                raise VerificationError("Fabric controller did not prove shared rows were written once")
        if not args.mirror_probe_command:
            raise VerificationError("--mirror-probe-command is required")
        result = poll_mirror_convergence(
            lambda: _command_json(args.mirror_probe_command),
            {"stale_derived_rows_deleted": True},
            timeout_seconds=args.timeout_seconds,
            interval_seconds=args.poll_interval,
        )
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "controller": controller,
                    "mirror": result,
                    "claims_limited_to_mirror_tables": list(MIRROR_TABLES),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
