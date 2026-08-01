"""
Policy binding SDK + domains (ADR-0010 §7.2).

Public API:
    Field, PolicySchema, validate_and_clamp, bind_policy, discovery_manifest
    DOMAINS  — registry of domain schema builders (add your own in domains/)
"""

from .binding import (  # noqa: F401
    Field, PolicySchema, ValidationResult,
    validate_and_clamp, bind_policy, discovery_manifest,
)
from .domains import DOMAINS  # noqa: F401
