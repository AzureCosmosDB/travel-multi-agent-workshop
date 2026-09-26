from __future__ import annotations

import sys
import unittest
from pathlib import Path


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from src.app.traveller_context import (  # noqa: E402
    add_active_trip_context,
    build_traveller_context,
    render_supervisor_prompt,
)


class TravellerContextTests(unittest.TestCase):
    def test_persisted_preferences_are_safe_and_override_inferred_conflicts(self):
        context = build_traveller_context(
            {
                "name": "Tony Stark",
                "email": "tony@example.com",
                "preferences": {
                    "dietary": "vegetarian",
                    "unknownFutureKey": "keep-me",
                },
            },
            "tony",
            {"content": "Tony prefers steak and window seats."},
        )

        prompt = render_supervisor_prompt("BASE", context)

        self.assertEqual(
            context["profile"]["preferences"],
            {"dietary": "vegetarian", "unknownFutureKey": "keep-me"},
        )
        self.assertNotIn("tony@example.com", prompt)
        self.assertIn("persisted profile", prompt.lower())
        self.assertIn("authoritative for overlapping preference keys", prompt)
        self.assertIn("Conversational memory is inferred context", prompt)
        self.assertIn("Tony prefers steak and window seats.", prompt)

    def test_omitted_profile_fields_are_not_synthesized(self):
        context = build_traveller_context(
            {"preferences": {"dietary": "vegetarian"}},
            "tony",
            None,
        )

        self.assertEqual(
            context["profile"],
            {
                "userId": "tony",
                "preferences": {"dietary": "vegetarian"},
            },
        )

    def test_resolved_active_trip_is_projected_and_rendered_as_authoritative(self):
        context = add_active_trip_context(
            {},
            {
                "tripId": "trip-tony-lisbon",
                "destination": "Lisbon, Portugal",
                "startDate": "2026-11-10",
                "endDate": "2026-11-14",
                "status": "planning",
                "itinerary": [{"day": 1}],
                "tenantId": "marvel",
            },
        )

        prompt = render_supervisor_prompt("BASE", context)

        self.assertIn("authoritative saved trip referenced by this request", prompt)
        self.assertIn("call `create_or_update_itinerary` directly", prompt)
        self.assertIn("call `find_places`, choose a concrete returned place", prompt)
        self.assertIn("never persist a generic placeholder", prompt)
        self.assertIn("Do not ask the traveller to identify or confirm", prompt)
        self.assertIn("Preserve the saved dates", prompt)
        self.assertIn('"tripId": "trip-tony-lisbon"', prompt)
        self.assertNotIn('"itinerary":', prompt)
        self.assertNotIn('"tenantId":', prompt)

    def test_unresolved_trip_does_not_add_active_trip_instruction(self):
        prompt = render_supervisor_prompt(
            "BASE",
            add_active_trip_context({}, None),
        )

        self.assertNotIn("# Trusted Active Trip", prompt)
        self.assertIn("# Trusted Current-Traveller Context", prompt)

    def test_supervisor_rule_discovers_unnamed_places_before_trip_update(self):
        prompt_path = PYTHON_ROOT / "src" / "app" / "prompts" / "supervisor.prompty"
        prompt = prompt_path.read_text(encoding="utf-8")

        self.assertIn("including breakfast, lunch, or dinner", prompt)
        self.assertIn("first call `recall_memories`", prompt)
        self.assertIn("choose a concrete suitable place from the returned results", prompt)
        self.assertIn("Do not save a generic description or placeholder", prompt)
        self.assertIn("If the user names the exact place", prompt)


if __name__ == "__main__":
    unittest.main()
