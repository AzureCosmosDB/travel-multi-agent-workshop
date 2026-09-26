from __future__ import annotations

import sys
import unittest
from pathlib import Path


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from src.app.trip_planning import (  # noqa: E402
    TripRequestConflictError,
    TripRequestValidationError,
    TripSessionNotFoundError,
    start_trip_with_compensation,
    validate_trip_request,
)


class StartTripValidationTests(unittest.TestCase):
    def test_invalid_request_id_is_rejected_before_writes(self):
        with self.assertRaises(TripRequestValidationError):
            start_trip_with_compensation(
                tenant_id="marvel",
                user_id="tony",
                destination="Rome, Italy",
                start_date="2026-10-10",
                end_date="2026-10-14",
                active_agent="orchestrator",
                title=None,
                request_id="bad id",
                create_session=lambda *args, **kwargs: self.fail("must not write"),
                create_trip=lambda **kwargs: self.fail("must not write"),
                get_trip=lambda *args: None,
                get_session=lambda *args: None,
                delete_trip=lambda *args: None,
                delete_session=lambda *args: None,
            )

    def test_exact_dates_and_route_identity_are_used_for_session_validation(self):
        calls = []

        destination = validate_trip_request(
            tenant_id="marvel",
            user_id="tony",
            destination="  Rome, Italy  ",
            start_date="2026-10-10",
            end_date="2026-10-14",
            session_id="session-1",
            get_session=lambda *args: calls.append(args) or {"sessionId": args[0]},
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
                get_session=lambda *args: None,
            )

    def test_invalid_or_reversed_dates_are_rejected_before_writes(self):
        create_calls = []
        for start_date, end_date in (
            ("", "2026-10-14"),
            ("20261010", "20261014"),
            ("2026-02-30", "2026-03-01"),
            ("2026-10-14", "2026-10-10"),
        ):
            with self.assertRaises(TripRequestValidationError):
                start_trip_with_compensation(
                    tenant_id="marvel",
                    user_id="tony",
                    destination="Rome, Italy",
                    start_date=start_date,
                    end_date=end_date,
                    active_agent="orchestrator",
                    title=None,
                    create_session=lambda *args: create_calls.append(args),
                    create_trip=lambda **kwargs: "trip-1",
                    get_trip=lambda *args: {},
                    delete_trip=lambda *args: None,
                    delete_session=lambda *args: None,
                )
        self.assertEqual(create_calls, [])


class StartTripCompensationTests(unittest.TestCase):
    def _idempotent_store(self):
        sessions = {}
        trips = {}

        def create_session(user_id, tenant_id, active_agent, title, **kwargs):
            session_id = kwargs["session_id"]
            session = {
                "id": session_id,
                "sessionId": session_id,
                "tenantId": tenant_id,
                "userId": user_id,
                "title": title or "New Conversation",
                "activeAgent": active_agent,
                "createdAt": "2026-09-23T00:00:00Z",
                "lastActivityAt": "2026-09-23T00:00:00Z",
                "startTripRequestId": kwargs["start_trip_request_id"],
                "startTripFingerprint": kwargs["start_trip_fingerprint"],
            }
            sessions[session_id] = session
            return session

        def create_trip(**kwargs):
            trip_id = kwargs["trip_id"]
            trips[trip_id] = {
                "id": trip_id,
                "tripId": trip_id,
                "tenantId": kwargs["tenant_id"],
                "userId": kwargs["user_id"],
                "sessionId": kwargs["session_id"],
                "destination": kwargs["destination"],
                "startDate": kwargs["start_date"],
                "endDate": kwargs["end_date"],
                "startTripRequestId": kwargs["start_trip_request_id"],
                "startTripFingerprint": kwargs["start_trip_fingerprint"],
            }
            return trip_id

        return sessions, trips, create_session, create_trip

    def test_same_request_id_returns_same_pair_and_one_logical_record(self):
        sessions, trips, create_session, create_trip = self._idempotent_store()
        arguments = {
            "tenant_id": "marvel",
            "user_id": "tony",
            "destination": "Rome, Italy",
            "start_date": "2026-10-10",
            "end_date": "2026-10-14",
            "active_agent": "orchestrator",
            "title": None,
            "request_id": "request-duplicate-123",
            "create_session": create_session,
            "create_trip": create_trip,
            "get_session": lambda session_id, *_: sessions.get(session_id),
            "get_trip": lambda trip_id, *_: trips.get(trip_id),
            "delete_trip": lambda *args: self.fail("must not compensate"),
            "delete_session": lambda *args: self.fail("must not compensate"),
        }

        first = start_trip_with_compensation(**arguments)
        second = start_trip_with_compensation(**arguments)

        self.assertEqual(first[0]["sessionId"], second[0]["sessionId"])
        self.assertEqual(first[1]["tripId"], second[1]["tripId"])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(trips), 1)

    def test_request_id_identity_is_scoped_by_tenant_and_user(self):
        sessions, trips, create_session, create_trip = self._idempotent_store()

        def start(tenant_id, user_id):
            return start_trip_with_compensation(
                tenant_id=tenant_id,
                user_id=user_id,
                destination="Rome, Italy",
                start_date="2026-10-10",
                end_date="2026-10-14",
                active_agent="orchestrator",
                title=None,
                request_id="request-shared-123",
                create_session=create_session,
                create_trip=create_trip,
                get_session=lambda session_id, *_: sessions.get(session_id),
                get_trip=lambda trip_id, *_: trips.get(trip_id),
                delete_trip=lambda *args: self.fail("must not compensate"),
                delete_session=lambda *args: self.fail("must not compensate"),
            )

        first = start("marvel", "tony")
        second = start("marvel", "pepper")

        self.assertNotEqual(first[0]["sessionId"], second[0]["sessionId"])
        self.assertNotEqual(first[1]["tripId"], second[1]["tripId"])

    def test_request_id_payload_conflict_is_rejected_without_overwrite(self):
        sessions, trips, create_session, create_trip = self._idempotent_store()
        common = {
            "tenant_id": "marvel",
            "user_id": "tony",
            "start_date": "2026-10-10",
            "end_date": "2026-10-14",
            "active_agent": "orchestrator",
            "title": None,
            "request_id": "request-conflict-123",
            "create_session": create_session,
            "create_trip": create_trip,
            "get_session": lambda session_id, *_: sessions.get(session_id),
            "get_trip": lambda trip_id, *_: trips.get(trip_id),
            "delete_trip": lambda *args: self.fail("must not compensate"),
            "delete_session": lambda *args: self.fail("must not compensate"),
        }
        start_trip_with_compensation(destination="Rome, Italy", **common)

        with self.assertRaises(TripRequestConflictError):
            start_trip_with_compensation(destination="Paris, France", **common)

        self.assertEqual(next(iter(trips.values()))["destination"], "Rome, Italy")

    def test_idempotent_failure_does_not_delete_preexisting_session(self):
        sessions, trips, create_session, create_trip = self._idempotent_store()
        common = {
            "tenant_id": "marvel",
            "user_id": "tony",
            "destination": "Rome, Italy",
            "start_date": "2026-10-10",
            "end_date": "2026-10-14",
            "active_agent": "orchestrator",
            "title": None,
            "request_id": "request-preserve-123",
            "create_session": create_session,
            "create_trip": create_trip,
            "get_session": lambda session_id, *_: sessions.get(session_id),
            "get_trip": lambda trip_id, *_: trips.get(trip_id),
            "delete_trip": lambda *args: self.fail("must not delete"),
            "delete_session": lambda *args: self.fail("must not delete"),
        }
        start_trip_with_compensation(**common)
        stored_trip = trips.pop(next(iter(trips)))
        common["create_trip"] = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("retry failed")
        )

        with self.assertRaisesRegex(RuntimeError, "retry failed"):
            start_trip_with_compensation(**common)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(stored_trip["destination"], "Rome, Italy")

    def test_trip_failure_compensates_new_session(self):
        deleted = []

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
                create_trip=lambda **kwargs: (_ for _ in ()).throw(
                    RuntimeError("trip write failed")
                ),
                get_trip=lambda *args: None,
                delete_trip=lambda *args: self.fail("no trip ID was returned"),
                delete_session=lambda *args: deleted.append(args),
            )
        self.assertEqual(deleted, [("session-1", "marvel", "tony")])

    def test_success_persists_exact_dates_and_session_binding(self):
        created = []
        trip = {
            "tripId": "trip-1",
            "sessionId": "session-1",
            "startDate": "2026-10-10",
            "endDate": "2026-10-14",
        }

        session, actual_trip = start_trip_with_compensation(
            tenant_id="marvel",
            user_id="tony",
            destination=" Rome, Italy ",
            start_date="2026-10-10",
            end_date="2026-10-14",
            active_agent="orchestrator",
            title=None,
            create_session=lambda *args: {"sessionId": "session-1"},
            create_trip=lambda **kwargs: created.append(kwargs) or "trip-1",
            get_trip=lambda *args: trip,
            delete_trip=lambda *args: self.fail("must not compensate success"),
            delete_session=lambda *args: self.fail("must not compensate success"),
        )

        self.assertEqual(session["sessionId"], "session-1")
        self.assertIs(actual_trip, trip)
        self.assertEqual(created[0]["start_date"], "2026-10-10")
        self.assertEqual(created[0]["end_date"], "2026-10-14")
        self.assertEqual(created[0]["session_id"], "session-1")
        self.assertEqual(created[0]["days"], [])

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
                delete_trip=lambda *args: (_ for _ in ()).throw(
                    RuntimeError("trip cleanup failed")
                ),
                delete_session=lambda *args: deleted_sessions.append(args),
            )

        self.assertEqual(deleted_sessions, [])


if __name__ == "__main__":
    unittest.main()
