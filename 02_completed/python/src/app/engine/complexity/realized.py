"""
Realized-complexity signal (ADR-0010 §4.1, spike B6).

Two ways to judge a turn's complexity:

  * **Declared (keyword tier)** — classify the *user text* with hand-authored patterns
    BEFORE the turn runs. This is what the app's model-selection classifier does
    (`travel_agents.classify_turn_tier`): conservative — only short greetings become
    "trivial", so it downgrades very few turns and leaves real savings on the table.

  * **Measured (realized complexity)** — read what the turn ACTUALLY produced: the
    node-grain output tokens. A turn that emitted very few output tokens WAS trivial,
    regardless of how its prompt read. This is the signal the engine's counterfactual
    `model_fit` detector already uses.

This module makes the measured signal a first-class, reusable primitive and provides a
head-to-head comparison so the "finds more opportunity than the keyword tier" claim is
checkable on labeled data (see `_selftest`). It stays pure stdlib — a small mirror of the
app's classifier lives here so the comparison is self-contained (the app module carries
heavy runtime deps the engine deliberately avoids).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.costs import LOW_COMPLEXITY_OUTPUT

# --- measured signal --------------------------------------------------------------

def realized_tier(output_tokens: int, low: int = LOW_COMPLEXITY_OUTPUT) -> str:
    """Measured tier from what the turn actually produced."""
    return "trivial" if output_tokens <= low else "substantive"


# --- declared signal (a faithful, stdlib mirror of the app's keyword classifier) --

_TRIVIAL_PATTERNS = [
    r"^(hi|hello|hey|yo|greetings|good (morning|afternoon|evening))\b",
    r"^(thanks|thank you|thx|ty|cheers|much appreciated|appreciate it|appreciated)\b",
    r"^(ok|okay|k|kk|sure|yes|yep|yeah|yup|no|nope|nah|alright|right|fine)\b",
    r"^(great|cool|awesome|perfect|nice|good|wonderful|excellent|fantastic|lovely|brilliant)\b",
    r"^(got it|sounds good|sounds great|looks good|that works|works for me|makes sense|will do|no worries|no problem)\b",
    r"^(bye|goodbye|see you|see ya|later|take care)\b",
]
_COMPLEX_PATTERNS = [r"itinerary", r"plan (my|the|a|our) (trip|day|days|vacation|holiday)",
                     r"build (me )?(an? )?itinerary", r"day[- ]by[- ]day", r"full (trip )?plan"]
_TRIVIAL_MAX_WORDS = 6


def keyword_tier(text: str) -> str:
    """Declared tier from the user text — mirrors app `classify_turn_tier` (trivial/routine/complex)."""
    t = (text or "").strip().lower()
    if not t:
        return "routine"
    if any(re.search(p, t) for p in _COMPLEX_PATTERNS):
        return "complex"
    words = re.findall(r"[a-z0-9']+", t)
    if len(words) <= _TRIVIAL_MAX_WORDS and any(re.search(p, t) for p in _TRIVIAL_PATTERNS):
        return "trivial"
    return "routine"


# --- comparison -------------------------------------------------------------------

@dataclass
class LabeledTurn:
    """A turn with both signals available plus ground truth (for the comparison)."""
    text: str
    output_tokens: int
    truly_trivial: bool     # constructed ground truth (the turn really was low-complexity)


def compare_coverage(turns: list[LabeledTurn], low: int = LOW_COMPLEXITY_OUTPUT) -> dict:
    """Head-to-head: how many truly-trivial turns each signal catches (recall), and how
    many truly-substantive turns each wrongly downgrades (false-downgrade / precision)."""
    truly = [t for t in turns if t.truly_trivial]
    kw_caught = [t for t in truly if keyword_tier(t.text) == "trivial"]
    me_caught = [t for t in truly if realized_tier(t.output_tokens, low) == "trivial"]
    kw_false = [t for t in turns if not t.truly_trivial and keyword_tier(t.text) == "trivial"]
    me_false = [t for t in turns if not t.truly_trivial and realized_tier(t.output_tokens, low) == "trivial"]
    n_truly = len(truly) or 1
    return {
        "truly_trivial": len(truly),
        "keyword_caught": len(kw_caught), "keyword_recall": round(len(kw_caught) / n_truly, 4),
        "measured_caught": len(me_caught), "measured_recall": round(len(me_caught) / n_truly, 4),
        "extra_opportunities": len(me_caught) - len(kw_caught),
        "keyword_false_downgrades": len(kw_false), "measured_false_downgrades": len(me_false),
    }
