"""Layer 1 — Instrumentation: capture telemetry at the agent-execution grain."""

from .node_grain import (  # noqa: F401
    node_grain_records,
    node_from_event,
    current_turn_aggregate,
    reconciles,
    extract_msg_usage,
)
