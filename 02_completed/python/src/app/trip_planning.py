from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from typing import Any, Callable, Optional


class TripRequestValidationError(ValueError):
    pass


class TripSessionNotFoundError(LookupError):
    pass


class StartTripConflictError(RuntimeError):
    pass


def validate_request_id(request_id: Optional[str]) -> Optional[str]:
    if request_id is None:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", request_id):
        raise TripRequestValidationError(
            "requestId must be 8-128 characters using letters, numbers, '.', '_', ':', or '-'"
        )
    return request_id


def _operation_identity(
    tenant_id: str,
    user_id: str,
    request_id: str,
) -> tuple[str, str]:
    digest = hashlib.sha256(
        f"{tenant_id}\0{user_id}\0{request_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"session_request_{digest}", f"trip_request_{digest}"


def _operation_fingerprint(
    *,
    destination: str,
    start_date: str,
    end_date: str,
    active_agent: str,
    title: Optional[str],
) -> str:
    canonical_payload = json.dumps(
        {
            "activeAgent": active_agent,
            "destination": destination,
            "endDate": end_date,
            "startDate": start_date,
            "title": title or "New Conversation",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def _assert_matching_operation(
    record: dict[str, Any],
    *,
    request_id: str,
    fingerprint: str,
) -> None:
    if (
        record.get("startTripRequestId") != request_id
        or record.get("startTripFingerprint") != fingerprint
    ):
        raise StartTripConflictError(
            "requestId was already used with a different Start Trip payload"
        )


def validate_trip_request(
    *,
    tenant_id: str,
    user_id: str,
    destination: str,
    start_date: str,
    end_date: str,
    session_id: Optional[str],
    get_session: Callable[[str, str, str], object | None],
) -> str:
    cleaned_destination = destination.strip()
    if not cleaned_destination:
        raise TripRequestValidationError("Destination is required")

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start_date or "") or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", end_date or ""
    ):
        raise TripRequestValidationError(
            "startDate and endDate must be valid ISO dates (YYYY-MM-DD)"
        )
    try:
        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise TripRequestValidationError(
            "startDate and endDate must be valid ISO dates (YYYY-MM-DD)"
        ) from exc
    if parsed_end < parsed_start:
        raise TripRequestValidationError("endDate must be on or after startDate")

    if session_id and not get_session(session_id, tenant_id, user_id):
        raise TripSessionNotFoundError(
            "Session not found for the specified tenant and user"
        )

    return cleaned_destination


def start_trip_with_compensation(
    *,
    tenant_id: str,
    user_id: str,
    destination: str,
    start_date: str,
    end_date: str,
    active_agent: str,
    title: Optional[str],
    create_session: Callable[..., Any],
    create_trip: Callable[..., str],
    get_trip: Callable[[str, str, str], Optional[dict[str, Any]]],
    delete_trip: Callable[[str, str, str], None],
    delete_session: Callable[[str, str, str], None],
    request_id: Optional[str] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a session and its bound trip, compensating legacy operations on failure."""
    cleaned_destination = validate_trip_request(
        tenant_id=tenant_id,
        user_id=user_id,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        session_id=None,
        get_session=lambda *_: None,
    )
    request_id = validate_request_id(request_id)

    session_created = True
    trip_created = False
    fingerprint: Optional[str] = None
    session_id: Optional[str] = None
    deterministic_trip_id: Optional[str] = None
    if request_id:
        session_id, deterministic_trip_id = _operation_identity(
            tenant_id, user_id, request_id
        )
        fingerprint = _operation_fingerprint(
            destination=cleaned_destination,
            start_date=start_date,
            end_date=end_date,
            active_agent=active_agent,
            title=title,
        )
        session, session_created = create_session(
            user_id,
            tenant_id,
            active_agent,
            title,
            session_id=session_id,
            request_id=request_id,
            fingerprint=fingerprint,
            return_created=True,
        )
        _assert_matching_operation(
            session,
            request_id=request_id,
            fingerprint=fingerprint,
        )
    else:
        session = create_session(user_id, tenant_id, active_agent, title)
    session_id = session["sessionId"]
    trip_id: Optional[str] = None
    try:
        trip_kwargs = dict(
            user_id=user_id,
            tenant_id=tenant_id,
            destination=cleaned_destination,
            start_date=start_date,
            end_date=end_date,
            days=[],
            session_id=session_id,
        )
        if request_id:
            trip_kwargs.update(
                trip_id=deterministic_trip_id,
                request_id=request_id,
                fingerprint=fingerprint,
                return_created=True,
            )
        trip_result = create_trip(**trip_kwargs)
        if request_id:
            trip_id, trip_created = trip_result
        else:
            trip_id = trip_result
            trip_created = True
        trip = get_trip(trip_id, user_id, tenant_id)
        if not trip:
            raise RuntimeError("Created trip could not be read")
        if request_id and fingerprint:
            _assert_matching_operation(
                trip,
                request_id=request_id,
                fingerprint=fingerprint,
            )
        return session, trip
    except Exception:
        if request_id:
            raise
        if trip_id and trip_created:
            try:
                delete_trip(trip_id, user_id, tenant_id)
            except Exception as compensation_error:
                raise RuntimeError(
                    "Start-trip compensation failed while deleting the created trip; "
                    "the bound trip and session were preserved"
                ) from compensation_error
        if session_created:
            try:
                delete_session(session_id, tenant_id, user_id)
            except Exception as compensation_error:
                raise RuntimeError(
                    "Start-trip compensation failed while deleting the created session"
                ) from compensation_error
        raise
