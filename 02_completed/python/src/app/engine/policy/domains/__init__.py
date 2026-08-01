"""
Policy domains (ADR-0010 §7.2). Each domain declares its own typed schema.

To ADD A DOMAIN (teaching extension point): create a module here and register a
builder `(**runtime_ctx) -> PolicySchema`:

    from . import DOMAINS
    from ..binding import Field, PolicySchema

    @DOMAINS.register("memory-retention")
    def build(**ctx) -> PolicySchema: ...

The registry holds *builders* because a schema's value domains are bound from the
app's runtime registry (e.g. its real deployment names).
"""

from ...core import Registry

DOMAINS = Registry("policy_domains")

from . import model_selection  # noqa: F401,E402  (registers the domain)
