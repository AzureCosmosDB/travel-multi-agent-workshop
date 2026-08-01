"""
Agent-centric analysis & optimization engine (ADR-0010).

Reference implementation of the engine whose pieces were de-risked as spikes under
`analytics/spikes/` (see ADR-0012). Each functional area is its own small package;
importing this top-level package wires up every extension registry.

    from src.app.engine import detectors, projection, policy, analyst, autonomy, learning, simulation
    nodes = simulation.simulate(seed=1, n_turns=1000)
    findings = detectors.run_all(nodes)

See `README.md` for the folder map and how to add a detector / policy domain / projection.
"""

from .core import NodeExec, Registry  # noqa: F401

# Import subpackages so their extension registries populate on import.
from . import instrumentation  # noqa: F401
from . import detectors        # noqa: F401
from . import policy           # noqa: F401
from . import projection       # noqa: F401
from . import analyst          # noqa: F401
from . import autonomy         # noqa: F401
from . import learning         # noqa: F401
from . import simulation       # noqa: F401
from . import scorecard        # noqa: F401
from . import complexity       # noqa: F401
from . import seams            # noqa: F401
from . import codecontext      # noqa: F401
from . import quality          # noqa: F401

from .pipeline import analyze, OPPORTUNITY_SEAMS, default_analyst  # noqa: F401,E402
