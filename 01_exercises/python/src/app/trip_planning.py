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


class TripRequestConflictError(RuntimeError):
    pass


def _validate_request_id(request_id: Optional[str]) -> Optional[str]:
    if request_id is None:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", request_id):
        raise TripRequestValidationError(
            "requestId must be 8-128 characters using letters, numbers, '.', '_', ':', or '-'"
        )
    return request_id


def _operation_details(
    *,
    tenant_id: str,
    user_id: str,
    request_id: str,
    destination: str,
    start_date: str,
    end_date: str,
    active_agent: str,
    title: Optional[str],
) -> tuple[str, str, str]:
    identity_digest = hashlib.sha256(
        f"{tenant_id}\0{user_id}\0{request_id}".encode("utf-8")
    ).hexdigest()
    fingerprint_payload = {
        "activeAgent": active_agent,
        "destination": destination,
        "endDate": end_date,
        "startDate": start_date,
        "title": title or "New Conversation",
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return (
        f"session_{identity_digest[:24]}",
        f"trip_{identity_digest[24:48]}",
        fingerprint,
    )


def _assert_matching_operation(
    record: Optional[dict[str, Any]],
    *,
    request_id: str,
    fingerprint: str,
) -> None:
    if not record:
        return
    if (
        record.get("startTripRequestId") != request_id
        or record.get("startTripFingerprint") != fingerprint
    ):
        raise TripRequestConflictError(
            "requestId has already been used with a different Start Trip payload"
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
    request_id: Optional[str] = None,
    create_session: Callable[[str, str, str, Optional[str]], dict[str, Any]],
    create_trip: Callable[..., str],
    get_trip: Callable[[str, str, str], Optional[dict[str, Any]]],
    get_session: Optional[
        Callable[[str, str, str], Optional[dict[str, Any]]]
    ] = None,
    delete_trip: Callable[[str, str, str], None],
    delete_session: Callable[[str, str, str], None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a session and bound trip, with optional operation idempotency."""
    cleaned_destination = validate_trip_request(
        tenant_id=tenant_id,
        user_id=user_id,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        session_id=None,
        get_session=lambda *_: None,
    )
    request_id = _validate_request_id(request_id)

    if request_id:
        if get_session is None:
            raise RuntimeError("Idempotent Start Trip requires session lookup")
        session_id, deterministic_trip_id, fingerprint = _operation_details(
            tenant_id=tenant_id,
            user_id=user_id,
            request_id=request_id,
            destination=cleaned_destination,
            start_date=start_date,
            end_date=end_date,
            active_agent=active_agent,
            title=title,
        )
        existing_session = get_session(session_id, tenant_id, user_id)
        existing_trip = get_trip(deterministic_trip_id, user_id, tenant_id)
        _assert_matching_operation(
            existing_session,
            request_id=request_id,
            fingerprint=fingerprint,
        )
        _assert_matching_operation(
            existing_trip,
            request_id=request_id,
            fingerprint=fingerprint,
        )
        if existing_session and existing_trip:
            return existing_session, existing_trip
        session = existing_session or create_session(
            user_id,
            tenant_id,
            active_agent,
            title,
            session_id=session_id,
            start_trip_request_id=request_id,
            start_trip_fingerprint=fingerprint,
        )
    else:
        deterministic_trip_id = None
        fingerprint = None
        session = create_session(user_id, tenant_id, active_agent, title)
        session_id = session["sessionId"]

    trip_id: Optional[str] = None
    try:
        trip_arguments = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "destination": cleaned_destination,
            "start_date": start_date,
            "end_date": end_date,
            "days": [],
            "session_id": session_id,
        }
        if request_id:
            trip_arguments.update({
                "trip_id": deterministic_trip_id,
                "start_trip_request_id": request_id,
                "start_trip_fingerprint": fingerprint,
            })
        trip_id = create_trip(**trip_arguments)
        trip = get_trip(trip_id, user_id, tenant_id)
        if not trip:
            raise RuntimeError("Created trip could not be read")
        if request_id:
            _assert_matching_operation(
                trip,
                request_id=request_id,
                fingerprint=fingerprint,
            )
        return session, trip
    except Exception:
        if request_id:
            # Deterministic records may have been created by a concurrent delivery.
            # Leave partial state for a safe retry rather than deleting shared data.
            raise
        if trip_id:
            try:
                delete_trip(trip_id, user_id, tenant_id)
            except Exception as compensation_error:
                raise RuntimeError(
                    "Start-trip compensation failed while deleting the created trip; "
                    "the bound trip and session were preserved"
                ) from compensation_error
        try:
            delete_session(session_id, tenant_id, user_id)
        except Exception as compensation_error:
            raise RuntimeError(
                "Start-trip compensation failed while deleting the created session"
            ) from compensation_error
        raise
