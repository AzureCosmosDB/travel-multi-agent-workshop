"""
Code-context provider (ADR-0010 §7/§8, spike B12) — read-only retrieval for the analyst.

    from src.app.engine import codecontext
    provider = codecontext.InMemoryProvider({"path.py": source_text})
    ctx = provider.retrieve("introduce-model-selector", hints=["select_deployment_for_turn"])
    draft = codecontext.scaffold_diff(ctx, "route trivial turns to a cheaper model")

The provider is READ-ONLY (no write path). `FileBackedProvider` adds a strict allowlist
so the analyst can be pointed at a live repo without any risk of reading/mutating outside
the declared code seam.
"""

from __future__ import annotations

from .base import (  # noqa: F401
    CodeContext,
    CodeContextProvider,
    CodeSnippet,
    scaffold_diff,
)
from .filebacked import FileBackedProvider  # noqa: F401
from .inmemory import InMemoryProvider  # noqa: F401
