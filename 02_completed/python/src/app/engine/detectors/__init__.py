"""
Detectors (ADR-0010 §6). Importing this package registers the built-in detectors.

Public API:
    DETECTORS      — the registry (add your own with @DETECTORS.register(...))
    Detection      — the result type
    run_all(nodes) — run every registered detector over node-grain data
"""

from .base import DETECTORS, Detection, run_all, KINDS  # noqa: F401

# Import detector modules so their @register decorators run.
from . import structural  # noqa: F401,E402
from . import counterfactual  # noqa: F401,E402
from . import statistical  # noqa: F401,E402
