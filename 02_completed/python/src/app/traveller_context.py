"""Request-scoped, model-visible traveller context helpers."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


_current_traveller_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "current_traveller_context",
    default=None,
)

_ADDRESS_FIELDS = ("city", "state", "country")
_ACTIVE_TRIP_FIELDS = ("tripId", "destination", "startDate", "endDate", "status")


def project_safe_user_profile(
    profile_document: Any,
    route_user_id: str,
) -> dict[str, Any]:
    """Project only model-safe profile fields, trusting the route for identity."""
    profile: dict[str, Any] = {"userId": route_user_id}
    if not isinstance(profile_document, Mapping):
        return profile

    name = profile_document.get("name")
    if isinstance(name, str):
        profile["name"] = name

    age = profile_document.get("age")
    if isinstance(age, int) and not isinstance(age, bool):
        profile["age"] = age

    gender = profile_document.get("gender")
    if isinstance(gender, str):
        profile["gender"] = gender

    source_address = profile_document.get("address")
    if isinstance(source_address, Mapping):
        address = {
            field: source_address[field]
            for field in _ADDRESS_FIELDS
            if isinstance(source_address.get(field), str)
        }
        if address:
            profile["address"] = address
    preferences = profile_document.get("preferences")
    if isinstance(preferences, Mapping):
        profile["preferences"] = {
            str(key): value
            for key, value in preferences.items()
            if isinstance(key, str)
            and isinstance(value, (str, int, float, bool))
            and not isinstance(value, type(None))
        }

    return profile


def normalize_user_summary(summary: Any) -> Mapping[str, Any] | None:
    """Normalize toolkit summary results to one mapping."""
    if isinstance(summary, list):
        summary = summary[0] if summary else None
    if hasattr(summary, "model_dump"):
        summary = summary.model_dump()
    return summary if isinstance(summary, Mapping) else None


def build_traveller_context(
    profile_document: Any,
    route_user_id: str,
    summary: Any,
) -> dict[str, Any]:
    """Build the only traveller data exposed to the supervisor prompt."""
    normalized_summary = normalize_user_summary(summary)
    summary_content = (
        normalized_summary.get("content")
        if normalized_summary is not None
        else None
    )
    return {
        "profile": project_safe_user_profile(profile_document, route_user_id),
        "memory_summary": (
            summary_content.strip()
            if isinstance(summary_content, str) and summary_content.strip()
            else None
        ),
    }


def project_safe_active_trip(active_trip: Any) -> dict[str, str] | None:
    """Project only the saved-trip fields needed by the supervisor."""
    if not isinstance(active_trip, Mapping):
        return None

    projected = {
        field: value
        for field in _ACTIVE_TRIP_FIELDS
        if isinstance((value := active_trip.get(field)), str) and value.strip()
    }
    if "tripId" not in projected:
        fallback_id = active_trip.get("id")
        if isinstance(fallback_id, str) and fallback_id.strip():
            projected["tripId"] = fallback_id
    return projected if "tripId" in projected else None


def add_active_trip_context(
    context: Mapping[str, Any],
    active_trip: Any,
) -> dict[str, Any]:
    """Return request context with a safely projected resolved trip, if any."""
    updated = dict(context)
    projected = project_safe_active_trip(active_trip)
    if projected is None:
        updated.pop("active_trip", None)
    else:
        updated["active_trip"] = projected
    return updated


def extract_summary_embedding(summary: Any) -> list[float] | None:
    """Return a summary preference embedding when one is present."""
    normalized_summary = normalize_user_summary(summary)
    embedding = (
        normalized_summary.get("embedding")
        if normalized_summary is not None
        else None
    )
    if isinstance(embedding, list) and all(
        isinstance(value, (int, float)) for value in embedding
    ):
        return embedding
    return None


@contextmanager
def use_traveller_context(context: dict[str, Any]) -> Iterator[None]:
    """Set traveller context for one request and reliably clear it afterward."""
    token = _current_traveller_context.set(context)
    try:
        yield
    finally:
        _current_traveller_context.reset(token)


def render_supervisor_prompt(
    base_prompt: str,
    context: Mapping[str, Any] | None,
) -> str:
    """Render transient server context into the model prompt only."""
    if context is None:
        return base_prompt

    profile = context.get("profile")
    safe_profile = profile if isinstance(profile, Mapping) else {}
    summary = context.get("memory_summary")
    summary_text = (
        summary
        if isinstance(summary, str) and summary.strip()
        else "No inferred conversational memory is available."
    )
    rendered = (
        f"{base_prompt}\n\n"
        "# Trusted Current-Traveller Context\n"
        "The persisted profile was resolved by the server and is authoritative for "
        "overlapping preference keys. Conversational memory is inferred context: use "
        "it only for facts absent from the persisted profile or explicitly scoped to "
        "a particular trip or conversation.\n"
        f"Persisted profile: {json.dumps(dict(safe_profile), ensure_ascii=True, sort_keys=True)}\n"
        "Inferred conversational memory:\n"
        f"{summary_text}"
    )
    active_trip = project_safe_active_trip(context.get("active_trip"))
    if active_trip is None:
        return rendered

    return (
        f"{rendered}\n\n"
        "# Trusted Active Trip\n"
        "The server safely resolved the authoritative saved trip referenced by this "
        "request. Keep using its tripId. Do not ask the traveller to identify or "
        "confirm the trip or dates again. If the change requires selecting an unnamed "
        "hotel, activity, restaurant, or meal place, recall relevant preferences and "
        "call `find_places`, choose a concrete returned place, then call "
        "`create_or_update_itinerary`; never persist a generic placeholder. Otherwise, "
        "call `create_or_update_itinerary` directly. Do not create a new trip. Preserve "
        "the saved dates unless the traveller explicitly asks to change them.\n"
        f"Active trip: {json.dumps(active_trip, ensure_ascii=True, sort_keys=True)}"
    )
