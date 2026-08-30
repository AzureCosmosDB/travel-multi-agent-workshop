"""Compatibility facade for the optimization apply-loop services.

02_completed splits the apply-loop engine across ``optimization_policy`` /
``optimization_governance`` / ``optimization_recommendations``. This thin module
keeps the Module 08 decision and model-selection API on one stable import path.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from src.app.services.azure_open_ai import (
    AZURE_OPENAI_DEPLOYMENT,
    get_chat_model,
)
from src.app.services.optimization_policy import get_active_policy

logger = logging.getLogger(__name__)

MODEL_SELECTION_SCENARIO = "model-selection"

_DEFAULT_TRIVIAL_PATTERNS = [
    r"^(hi|hello|hey|yo|greetings|good (morning|afternoon|evening))\b",
    r"^(thanks|thank you|thx|ty|cheers|much appreciated|appreciate it|appreciated)\b",
    r"^(ok|okay|k|kk|sure|yes|yep|yeah|yup|no|nope|nah|alright|right|fine)\b",
    r"^(great|cool|awesome|perfect|nice|good|wonderful|excellent|fantastic|lovely|brilliant)\b",
    r"^(got it|sounds good|sounds great|looks good|that works|works for me|makes sense|will do|no worries|no problem)\b",
    r"^(bye|goodbye|see you|see ya|later|take care)\b",
]
_DEFAULT_COMPLEX_PATTERNS = [
    r"itinerary",
    r"plan (my|the|a|our) (trip|day|days|vacation|holiday)",
    r"build (me )?(an? )?itinerary",
    r"day[- ]by[- ]day",
    r"full (trip )?plan",
]
_DEFAULT_TRIVIAL_MAX_WORDS = 6


def _latest_user_text(messages: Any) -> str:
    """Return the most recent human/user message text."""
    for message in reversed(list(messages or [])):
        if isinstance(message, dict):
            role, content = message.get("role"), message.get("content")
        else:
            role, content = getattr(message, "type", None), getattr(message, "content", None)
        if role in ("human", "user") and isinstance(content, str):
            return content
    return ""


def classify_complexity_tier(text: str, classifier: Optional[dict[str, Any]] = None) -> str:
    """Classify a turn conservatively as trivial, routine, or complex."""
    classifier = classifier or {}
    trivial_max = int(classifier.get("trivial_max_words", _DEFAULT_TRIVIAL_MAX_WORDS))
    trivial_patterns = classifier.get("trivial_patterns", _DEFAULT_TRIVIAL_PATTERNS)
    complex_patterns = classifier.get("complex_patterns", _DEFAULT_COMPLEX_PATTERNS)

    normalized = (text or "").strip().lower()
    if not normalized:
        return "routine"
    if any(re.search(pattern, normalized) for pattern in complex_patterns):
        return "complex"

    words = re.findall(r"[a-z0-9']+", normalized)
    if len(words) <= trivial_max and any(
        re.search(pattern, normalized) for pattern in trivial_patterns
    ):
        return "trivial"
    return "routine"


def select_deployment_for_turn(messages: Any) -> tuple[str, str]:
    """Return (deployment_name, complexity_tier) from the active policy."""
    default = AZURE_OPENAI_DEPLOYMENT
    try:
        policy = get_active_policy(MODEL_SELECTION_SCENARIO)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read model-selection policy; using default model: %s", exc)
        policy = None

    if not policy:
        return default, "default"
    params = policy.get("params", {}) or {}
    if not params.get("enabled", False):
        return default, "default"

    complexity_tier = classify_complexity_tier(
        _latest_user_text(messages),
        params.get("classifier"),
    )
    deployment = (
        (params.get("complexity_tiers", {}) or {}).get(complexity_tier)
        or params.get("default_deployment")
        or default
    )
    return deployment, complexity_tier


def get_chat_model_for_turn(messages: Any):
    """Return the chat model selected by the active policy for this turn."""
    deployment, _complexity_tier = select_deployment_for_turn(messages)
    return get_chat_model(deployment)
