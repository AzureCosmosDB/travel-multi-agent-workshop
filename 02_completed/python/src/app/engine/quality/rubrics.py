"""
Per-agent quality rubrics (ADR-0010 §5.1, spike B9).

A **reference-free** rubric scores a response on its own merits — no gold answer — using
criteria appropriate to the *agent* that produced it. That matters in a multi-agent system:
"good" for the supervisor (did it delegate appropriately, stay helpful) is different from
"good" for find_places (are the recommendations relevant and grounded) or the itinerary
generator (is the plan complete and coherent).

Rubrics are registered on the `RUBRICS` registry, so adding one for a new agent is the
same one-line gesture used across the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core import Registry

RUBRICS = Registry("quality.rubrics")


@dataclass
class QualityRubric:
    """Reference-free scoring criteria for one agent's output."""
    agent: str
    dimension: str
    criteria: list[str]
    scale: tuple[int, int] = (1, 5)
    pass_threshold: int = 3          # score >= threshold => passed
    # Optional cheap heuristic signals (used by the deterministic judge + as LLM hints).
    expects_named_entities: bool = False   # should cite concrete place/hotel/restaurant names
    expects_structure: bool = False        # should be structured (e.g. day-by-day)


def get_rubric(agent: str) -> QualityRubric:
    """The agent's rubric, or a generic fallback so any agent can be judged."""
    try:
        return RUBRICS.get(agent)
    except KeyError:
        return QualityRubric(
            agent=agent, dimension="agent quality",
            criteria=["relevant to the user's travel need", "helpful and actionable",
                      "factually plausible (no obvious hallucination)"],
        )


RUBRICS.register("supervisor")(QualityRubric(
    agent="supervisor", dimension="routing · agent quality",
    criteria=[
        "addresses the user's request or asks an appropriate clarifying question",
        "delegates to / synthesizes specialist work rather than guessing",
        "stays helpful and on-topic without over-answering",
    ],
))

RUBRICS.register("find_places")(QualityRubric(
    agent="find_places", dimension="tool utilization · agent quality",
    criteria=[
        "recommendations are relevant to the stated destination and preferences",
        "names concrete places (hotels/restaurants/activities), not vague categories",
        "grounded — no invented or implausible venues",
    ],
    expects_named_entities=True,
))

RUBRICS.register("itinerary")(QualityRubric(
    agent="itinerary", dimension="workflow · agent quality",
    criteria=[
        "covers the requested span (e.g. day-by-day for the trip length)",
        "coherent ordering and realistic pacing",
        "complete — hotels, dining, and activities tied together",
    ],
    expects_structure=True,
))
