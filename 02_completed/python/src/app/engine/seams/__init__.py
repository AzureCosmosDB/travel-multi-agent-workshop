"""
Seam registry (ADR-0010 §7, spike B11) — the declared optimizable surface.

    from src.app.engine import seams
    seams.surface()                       # {"config": {...}, "prompt": {...}, "code": {...}}
    seams.render_recipe("config:model-selection",
                        {"enabled": True, "default_deployment": "gpt-5-mini",
                         "complexity_tiers": {"routine": "gpt-5-mini"}})   # -> a fail-closed policy doc

Add a seam in `catalog.py` (or your own module) with `register(Seam(...))`.
"""

from __future__ import annotations

# Import the catalog so its seams register on import.
from . import catalog  # noqa: F401
from .base import (  # noqa: F401
    SEAMS,
    Seam,
    find_seam,
    get_seam,
    list_seams,
    register,
    render_recipe,
    surface,
)
