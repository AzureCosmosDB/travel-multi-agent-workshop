"""
In-memory code-context provider (spike B12).

Deterministic, dependency-free retrieval over a supplied `{path: source_text}` map — the
engine's testable default. Retrieval is keyword-based over the seam target + hints; it
returns whole matching blocks (functions/regions), read-only.
"""

from __future__ import annotations

import re

from .base import CodeContext, CodeContextProvider, CodeSnippet


def _iter_defs(text: str):
    """Yield (symbol, start_line, end_line, block_text) for top-level python defs."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"^\s*def\s+(\w+)", ln)]
    for idx, s in enumerate(starts):
        end = (starts[idx + 1] - 1) if idx + 1 < len(starts) else len(lines) - 1
        symbol = re.match(r"^\s*def\s+(\w+)", lines[s]).group(1)
        yield symbol, s + 1, end + 1, "\n".join(lines[s:end + 1])


class InMemoryProvider(CodeContextProvider):
    """Read-only retrieval over an in-memory source map — no filesystem, no writes."""

    def __init__(self, sources: dict[str, str]):
        self._sources = dict(sources)

    def retrieve(self, seam_target: str, hints: list[str] | None = None) -> CodeContext:
        terms = [seam_target, *(hints or [])]
        terms = [t.lower() for t in terms if t]
        ctx = CodeContext(seam_target=seam_target)
        for path, text in self._sources.items():
            for symbol, start, end, block in _iter_defs(text):
                hay = f"{symbol}\n{block}".lower()
                if any(t in hay or t in symbol.lower() for t in terms):
                    ctx.snippets.append(CodeSnippet(path, symbol, start, end, block))
        return ctx
