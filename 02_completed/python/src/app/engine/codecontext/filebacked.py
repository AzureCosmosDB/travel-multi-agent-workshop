"""
File-backed code-context provider (spike B12).

Read-only retrieval from real repository files, guarded by a strict **allowlist**: the
provider can only ever read paths the app explicitly opts in, and it has no write path —
so wiring the analyst to a live repo cannot leak or mutate anything outside the declared
code seam. Used by the app; the engine's own tests use `InMemoryProvider`.
"""

from __future__ import annotations

import os

from .base import CodeContext, CodeContextProvider
from .inmemory import InMemoryProvider


class FileBackedProvider(CodeContextProvider):
    """Read-only retrieval from `root`, restricted to an allowlist of relative paths."""

    def __init__(self, root: str, allowlist: list[str]):
        self._root = os.path.abspath(root)
        # Normalize + confine: only allowlisted files under root are ever readable.
        self._allow = []
        for rel in allowlist:
            full = os.path.abspath(os.path.join(self._root, rel))
            if os.path.commonpath([self._root, full]) == self._root:
                self._allow.append((rel, full))

    def _load(self) -> dict[str, str]:
        sources: dict[str, str] = {}
        for rel, full in self._allow:
            if os.path.isfile(full):
                with open(full, "r", encoding="utf-8") as fh:
                    sources[rel] = fh.read()
        return sources

    def retrieve(self, seam_target: str, hints: list[str] | None = None) -> CodeContext:
        # Delegate matching to the in-memory provider over the allowlisted files only.
        return InMemoryProvider(self._load()).retrieve(seam_target, hints)
