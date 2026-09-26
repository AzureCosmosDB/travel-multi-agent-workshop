from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
NAMES = (
    "ConversionFunnelReverseETL.ipynb",
    "ConversionFunnelReverseETL_solution.ipynb",
)


def _run(output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(HERE / "_gen_funnel_notebook.py"),
            "--output-dir",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_two_clean_processes_match_delivered_bytes() -> None:
    work = ROOT / ".local" / "fabric-tests" / "generation"
    shutil.rmtree(work, ignore_errors=True)
    first, second = work / "a", work / "b"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    try:
        assert _run(first).returncode == 0
        assert _run(second).returncode == 0
        for name in NAMES:
            a = (first / name).read_bytes()
            b = (second / name).read_bytes()
            delivered = (HERE / name).read_bytes()
            assert a == b == delivered
            assert hashlib.sha256(a).hexdigest() == hashlib.sha256(delivered).hexdigest()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_isolated_generation_rejects_stale_notebook_extra() -> None:
    work = ROOT / ".local" / "fabric-tests" / "stale-generation"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    (work / "stale.ipynb").write_text("{}\n", encoding="utf-8", newline="\n")
    try:
        result = _run(work)
        assert result.returncode != 0
        assert "unexpected notebook" in (result.stdout + result.stderr)
    finally:
        shutil.rmtree(work, ignore_errors=True)
