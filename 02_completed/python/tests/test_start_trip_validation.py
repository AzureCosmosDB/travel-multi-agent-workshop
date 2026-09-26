from __future__ import annotations

import sys
import unittest
from pathlib import Path


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from src.app.trip_planning import (  # noqa: E402
    StartTripConflictError,
    TripRequestValidationError,
    TripSessionNotFoundError,
    start_trip_with_compensation,
    validate_trip_request,
    validate_request_id,
)


class StartTripValidationTests(unittest.TestCase):
    def test_request_id_validation_is_optional_and_bounded(self):
        self.assertIsNone(validate_request_id(None))
        self.assertEqual(validate_request_id("attempt-123"), "attempt-123")
        for value in ("short", "contains space", "x" * 129):
            with self.assertRaises(TripRequestValidationError):
                validate_request_id(value)

    def test_exact_dates_and_route_identity_are_used_for_session_validation(self):
        calls = []

        def get_session(session_id, tenant_id, user_id):
            calls.append((session_id, tenant_id, user_id))
            return {"sessionId": session_id}

        destination = validate_trip_request(
            tenant_id="marvel",
            user_id="tony",
            destination="  Rome, Italy  ",
            start_date="2026-10-10",
            end_date="2026-10-14",
            session_id="session-1",
            get_session=get_session,
        )

        self.assertEqual(destination, "Rome, Italy")
        self.assertEqual(calls, [("session-1", "marvel", "tony")])

    def test_cross_user_or_unknown_session_is_rejected(self):
        with self.assertRaises(TripSessionNotFoundError):
            validate_trip_request(
                tenant_id="marvel",
                user_id="pepper",
                destination="Rome, Italy",
                start_date="2026-10-10",
                end_date="2026-10-14",
                session_id="tonys-session",
                get_session=lambda session_id, tenant_id, user_id: None,
            )

    def test_invalid_or_reversed_dates_are_rejected_before_session_lookup(self):
        calls = []
        invalid_ranges = [
            ("", "2026-10-14"),
            ("20261010", "20261014"),
            ("2026-02-30", "2026-03-01"),
            ("2026-10-14", "2026-10-10"),
        ]

        for start_date, end_date in invalid_ranges:
            with self.assertRaises(TripRequestValidationError):
                validate_trip_request(
                    tenant_id="marvel",
                    user_id="tony",
                    destination="Rome, Italy",
                    start_date=start_date,
                    end_date=end_date,
                    session_id="session-1",
                    get_session=lambda *args: calls.append(args),
                )

        self.assertEqual(calls, [])


class StartTripCompensationTests(unittest.TestCase):
    def test_validates_all_input_before_creating_session(self):
        create_calls = []

        with self.assertRaises(TripRequestValidationError):
            start_trip_with_compensation(
                tenant_id="marvel",
                user_id="tony",
                destination="Rome, Italy",
                start_date="2026-10-14",
                end_date="2026-10-10",
                active_agent="orchestrator",
                title=None,
                create_session=lambda *args: create_calls.append(args),
                create_trip=lambda **kwargs: "trip-1",
                get_trip=lambda *args: {},
                delete_trip=lambda *args: None,
                delete_session=lambda *args: None,
            )

        self.assertEqual(create_calls, [])

    def test_trip_failure_compensates_new_session(self):
        deleted = []

        def fail_trip(**kwargs):
            raise RuntimeError("trip write failed")

        with self.assertRaisesRegex(RuntimeError, "trip write failed"):
            start_trip_with_compensation(
                tenant_id="marvel",
                user_id="tony",
                destination="Rome, Italy",
                start_date="2026-10-10",
                end_date="2026-10-14",
                active_agent="orchestrator",
                title=None,
                create_session=lambda *args: {"sessionId": "session-1"},
                create_trip=fail_trip,
                get_trip=lambda *args: None,
                delete_trip=lambda *args: self.fail("no trip ID was returned"),
                delete_session=lambda *args: deleted.append(args),
            )

        self.assertEqual(deleted, [("session-1", "marvel", "tony")])

    def test_success_returns_bound_session_and_trip(self):
        session = {"sessionId": "session-1"}
        trip = {"tripId": "trip-1", "sessionId": "session-1"}

        actual_session, actual_trip = start_trip_with_compensation(
            tenant_id="marvel",
            user_id="tony",
            destination=" Rome, Italy ",
            start_date="2026-10-10",
            end_date="2026-10-14",
            active_agent="orchestrator",
            title=None,
            create_session=lambda *args: session,
            create_trip=lambda **kwargs: "trip-1",
            get_trip=lambda *args: trip,
            delete_trip=lambda *args: self.fail("must not compensate success"),
            delete_session=lambda *args: self.fail("must not compensate success"),
        )

        self.assertIs(actual_session, session)
        self.assertIs(actual_trip, trip)

    def test_readback_failure_compensates_trip_and_session(self):
        deleted_trips = []
        deleted_sessions = []

        with self.assertRaisesRegex(RuntimeError, "could not be read"):
            start_trip_with_compensation(
                tenant_id="marvel",
                user_id="tony",
                destination="Rome, Italy",
                start_date="2026-10-10",
                end_date="2026-10-14",
                active_agent="orchestrator",
                title=None,
                create_session=lambda *args: {"sessionId": "session-1"},
                create_trip=lambda **kwargs: "trip-1",
                get_trip=lambda *args: None,
                delete_trip=lambda *args: deleted_trips.append(args),
                delete_session=lambda *args: deleted_sessions.append(args),
            )

        self.assertEqual(deleted_trips, [("trip-1", "tony", "marvel")])
        self.assertEqual(deleted_sessions, [("session-1", "marvel", "tony")])

    def test_trip_cleanup_failure_preserves_bound_session(self):
        deleted_sessions = []

        def fail_trip_cleanup(*args):
            raise RuntimeError("trip cleanup failed")

        with self.assertRaisesRegex(
            RuntimeError,
            "compensation failed while deleting the created trip",
        ):
            start_trip_with_compensation(
                tenant_id="marvel",
                user_id="tony",
                destination="Rome, Italy",
                start_date="2026-10-10",
                end_date="2026-10-14",
                active_agent="orchestrator",
                title=None,
                create_session=lambda *args: {"sessionId": "session-1"},
                create_trip=lambda **kwargs: "trip-1",
                get_trip=lambda *args: None,
                delete_trip=fail_trip_cleanup,
                delete_session=lambda *args: deleted_sessions.append(args),
            )

        self.assertEqual(deleted_sessions, [])

    def test_same_request_id_returns_same_pair_and_one_logical_record(self):
        sessions = {}
        trips = {}

        def create_session(user_id, tenant_id, active_agent, title, **kwargs):
            session_id = kwargs["session_id"]
            created = session_id not in sessions
            sessions.setdefault(
                session_id,
                {
                    "sessionId": session_id,
                    "startTripRequestId": kwargs["request_id"],
                    "startTripFingerprint": kwargs["fingerprint"],
                },
            )
            return sessions[session_id], created

        def create_trip(**kwargs):
            trip_id = kwargs["trip_id"]
            created = trip_id not in trips
            trips.setdefault(
                trip_id,
                {
                    "tripId": trip_id,
                    "sessionId": kwargs["session_id"],
                    "startTripRequestId": kwargs["request_id"],
                    "startTripFingerprint": kwargs["fingerprint"],
                },
            )
            return trip_id, created

        arguments = dict(
            tenant_id="marvel",
            user_id="tony",
            destination="Rome, Italy",
            start_date="2026-10-10",
            end_date="2026-10-14",
            active_agent="orchestrator",
            title=None,
            request_id="attempt-123",
            create_session=create_session,
            create_trip=create_trip,
            get_trip=lambda trip_id, *_: trips.get(trip_id),
            delete_trip=lambda *args: self.fail("must not compensate success"),
            delete_session=lambda *args: self.fail("must not compensate success"),
        )

        first = start_trip_with_compensation(**arguments)
        second = start_trip_with_compensation(**arguments)

        self.assertEqual(first[0]["sessionId"], second[0]["sessionId"])
        self.assertEqual(first[1]["tripId"], second[1]["tripId"])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(trips), 1)

    def test_none_and_explicit_default_title_replay_same_operation(self):
        sessions = {}
        trips = {}

        def create_session(user_id, tenant_id, active_agent, title, **kwargs):
            session_id = kwargs["session_id"]
            created = session_id not in sessions
            sessions.setdefault(
                session_id,
                {
                    "sessionId": session_id,
                    "title": title or "New Conversation",
                    "startTripRequestId": kwargs["request_id"],
                    "startTripFingerprint": kwargs["fingerprint"],
                },
            )
            return sessions[session_id], created

        def create_trip(**kwargs):
            trip_id = kwargs["trip_id"]
            created = trip_id not in trips
            trips.setdefault(
                trip_id,
                {
                    "tripId": trip_id,
                    "startTripRequestId": kwargs["request_id"],
                    "startTripFingerprint": kwargs["fingerprint"],
                },
            )
            return trip_id, created

        common = dict(
            tenant_id="marvel",
            user_id="tony",
            destination="Rome, Italy",
            start_date="2026-10-10",
            end_date="2026-10-14",
            active_agent="orchestrator",
            request_id="attempt-title-default",
            create_session=create_session,
            create_trip=create_trip,
            get_trip=lambda trip_id, *_: trips.get(trip_id),
            delete_trip=lambda *args: self.fail("must not compensate success"),
            delete_session=lambda *args: self.fail("must not compensate success"),
        )

        first = start_trip_with_compensation(title=None, **common)
        replay = start_trip_with_compensation(title="New Conversation", **common)

        self.assertEqual(first, replay)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(trips), 1)

    def test_reused_request_id_with_different_payload_is_rejected(self):
        sessions = {}
        trips = {}

        def create_session(user_id, tenant_id, active_agent, title, **kwargs):
            session_id = kwargs["session_id"]
            created = session_id not in sessions
            sessions.setdefault(
                session_id,
                {
                    "sessionId": session_id,
                    "startTripRequestId": kwargs["request_id"],
                    "startTripFingerprint": kwargs["fingerprint"],
                },
            )
            return sessions[session_id], created

        def create_trip(**kwargs):
            trip_id = kwargs["trip_id"]
            trips[trip_id] = {
                "tripId": trip_id,
                "startTripRequestId": kwargs["request_id"],
                "startTripFingerprint": kwargs["fingerprint"],
            }
            return trip_id, True

        common = dict(
            tenant_id="marvel",
            user_id="tony",
            start_date="2026-10-10",
            end_date="2026-10-14",
            active_agent="orchestrator",
            title=None,
            request_id="attempt-123",
            create_session=create_session,
            create_trip=create_trip,
            get_trip=lambda trip_id, *_: trips.get(trip_id),
            delete_trip=lambda *args: None,
            delete_session=lambda *args: None,
        )
        start_trip_with_compensation(destination="Rome, Italy", **common)

        with self.assertRaises(StartTripConflictError):
            start_trip_with_compensation(destination="Paris, France", **common)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(trips), 1)

    def test_failure_does_not_delete_preexisting_idempotent_pair(self):
        deleted_trips = []
        deleted_sessions = []
        existing_session = {}

        def create_session(user_id, tenant_id, active_agent, title, **kwargs):
            existing_session.update(
                {
                    "sessionId": kwargs["session_id"],
                    "startTripRequestId": kwargs["request_id"],
                    "startTripFingerprint": kwargs["fingerprint"],
                }
            )
            return existing_session, False

        with self.assertRaisesRegex(RuntimeError, "readback failed"):
            start_trip_with_compensation(
                tenant_id="marvel",
                user_id="tony",
                destination="Rome, Italy",
                start_date="2026-10-10",
                end_date="2026-10-14",
                active_agent="orchestrator",
                title=None,
                request_id="attempt-123",
                create_session=create_session,
                create_trip=lambda **kwargs: (kwargs["trip_id"], False),
                get_trip=lambda *args: (_ for _ in ()).throw(
                    RuntimeError("readback failed")
                ),
                delete_trip=lambda *args: deleted_trips.append(args),
                delete_session=lambda *args: deleted_sessions.append(args),
            )

        self.assertEqual(deleted_trips, [])
        self.assertEqual(deleted_sessions, [])

    def test_readback_failure_preserves_partially_created_idempotent_pair(self):
        deleted_trips = []
        deleted_sessions = []

        def create_session(user_id, tenant_id, active_agent, title, **kwargs):
            return {
                "sessionId": kwargs["session_id"],
                "startTripRequestId": kwargs["request_id"],
                "startTripFingerprint": kwargs["fingerprint"],
            }, True

        with self.assertRaisesRegex(RuntimeError, "readback failed"):
            start_trip_with_compensation(
                tenant_id="marvel",
                user_id="tony",
                destination="Rome, Italy",
                start_date="2026-10-10",
                end_date="2026-10-14",
                active_agent="orchestrator",
                title=None,
                request_id="attempt-123",
                create_session=create_session,
                create_trip=lambda **kwargs: (kwargs["trip_id"], False),
                get_trip=lambda *args: (_ for _ in ()).throw(
                    RuntimeError("readback failed")
                ),
                delete_trip=lambda *args: deleted_trips.append(args),
                delete_session=lambda *args: deleted_sessions.append(args),
            )

        self.assertEqual(deleted_trips, [])
        self.assertEqual(deleted_sessions, [])


if __name__ == "__main__":
    unittest.main()
