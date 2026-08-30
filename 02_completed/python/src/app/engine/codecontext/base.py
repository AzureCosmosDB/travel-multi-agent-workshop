"""
Code-context provider (ADR-0010 §7 / §8, spike B12) — read-only retrieval.

The analyst may *propose* a code-seam change but must not *own* the codebase. This
provider is the one-way seam between the two: it retrieves relevant, read-only source
context for a code seam so the analyst can draft a diff grounded in real lines — and it
has **no write path at all**, so nothing here can modify the repository.

Two implementations (`inmemory.py`, `filebacked.py`) share this interface. `scaffold_diff`
turns retrieved snippets into a grounded unified-diff skeleton the analyst fills in; the
result is a *staged proposal* (guardrail: code seams are human-reviewed, never auto-applied).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CodeSnippet:
    """A read-only slice of source retrieved for context."""
    path: str
    symbol: str
    start_line: int
    end_line: int
    text: str


@dataclass
class CodeContext:
    """The read-only context returned for a seam target."""
    seam_target: str
    snippets: list[CodeSnippet] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.snippets)


class CodeContextProvider:
    """Read-only retrieval interface. Implementations expose `retrieve` only — no writes."""

    def retrieve(self, seam_target: str, hints: list[str] | None = None) -> CodeContext:
        raise NotImplementedError


def scaffold_diff(context: CodeContext, change_summary: str) -> str:
    """Build a grounded unified-diff SKELETON from retrieved context (a staged proposal).

    This is not an applied change — it anchors the analyst's draft to real file/line
    context so a human reviewer can see exactly where the proposed change lands.
    """
    if not context:
        return f"# No code context retrieved for '{context.seam_target}' — cannot draft a diff.\n"
    lines = [f"# Staged proposal (human-reviewed): {change_summary}",
             f"# Seam target: {context.seam_target}", ""]
    for s in context.snippets:
        lines.append(f"--- a/{s.path}")
        lines.append(f"+++ b/{s.path}")
        lines.append(f"@@ {s.symbol} (lines {s.start_line}-{s.end_line}) @@")
        for src_line in s.text.splitlines():
            lines.append(f" {src_line}")
        lines.append(f"+    # TODO(analyst): {change_summary}")
        lines.append("")
    return "\n".join(lines)
