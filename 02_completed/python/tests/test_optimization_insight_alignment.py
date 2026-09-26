from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from src.app import optimization_agent_api  # noqa: E402
from src.app.services import optimization_insights  # noqa: E402
from src.app.services import optimization_recommendations  # noqa: E402


class OptimizationInsightAlignmentTests(unittest.TestCase):
    def test_recommendation_uses_matching_engine_opportunity_saving(self):
        opportunities = [
            {
                "opportunity_id": "opp-modelfit-supervisor",
                "target": "model-selection",
                "saving": 13.17991,
            }
        ]
        cards = [
            {
                "scenario": "model-selection",
                "scenario_id": "model-selection",
                "opportunity_id": "opp-modelfit-supervisor",
                "title": "Capability-tiered model selection",
                "estimated_saving_usd": 0,
            }
        ]
        with (
            patch.object(
                optimization_agent_api,
                "_opportunities",
                return_value=(opportunities, 20.0, {}),
            ),
            patch.object(
                optimization_recommendations,
                "build_recommendations",
                return_value=cards,
            ),
            patch.object(
                optimization_recommendations,
                "build_turn_metrics",
                return_value={},
            ),
            patch.object(
                optimization_recommendations,
                "summarize_card_evidence",
                return_value="evidence",
            ),
            patch.object(
                optimization_recommendations,
                "card_caveat",
                return_value="caveat",
            ),
        ):
            rows = optimization_insights.build_recommendation_rows("marvel")

        recommendation = next(
            row for row in rows if row["type"] == "recommendation_card"
        )
        self.assertEqual(
            recommendation["opportunity_id"],
            "opp-modelfit-supervisor",
        )
        self.assertEqual(recommendation["estimated_saving_usd"], 13.17991)
        self.assertEqual(
            recommendation["card"]["opportunity_id"],
            "opp-modelfit-supervisor",
        )
        self.assertEqual(
            recommendation["card"]["estimated_saving_usd"],
            13.17991,
        )

    def test_duplicate_targets_match_by_stable_opportunity_identity(self):
        opportunities = [
            {
                "opportunity_id": "opp-other",
                "target": "model-selection",
                "saving": 99.0,
            },
            {
                "opportunity_id": "opp-modelfit-supervisor",
                "target": "model-selection",
                "saving": 7.25,
            },
        ]
        card = {
            "scenario": "model-selection",
            "scenario_id": "model-selection",
            "opportunity_id": "opp-modelfit-supervisor",
            "title": "Capability-tiered model selection",
            "estimated_saving_usd": 0,
        }
        for tenant in ("analytics", "marvel"):
            with (
                patch.object(
                    optimization_agent_api,
                    "_opportunities",
                    return_value=(opportunities, 20.0, {}),
                ),
                patch.object(
                    optimization_recommendations,
                    "build_recommendations",
                    return_value=[card],
                ),
                patch.object(
                    optimization_recommendations,
                    "build_turn_metrics",
                    return_value={},
                ),
                patch.object(
                    optimization_recommendations,
                    "summarize_card_evidence",
                    return_value="evidence",
                ),
                patch.object(
                    optimization_recommendations,
                    "card_caveat",
                    return_value="caveat",
                ),
            ):
                rows = optimization_insights.build_recommendation_rows(tenant)
            recommendation = next(
                row for row in rows if row["type"] == "recommendation_card"
            )
            self.assertEqual(recommendation["estimated_saving_usd"], 7.25)

    def test_missing_or_mismatched_identity_does_not_copy_projected_saving(self):
        opportunities = [{
            "opportunity_id": "opp-modelfit-supervisor",
            "target": "model-selection",
            "saving": 13.0,
        }]
        for opportunity_id in (None, "opp-mismatch"):
            card = {
                "scenario": "model-selection",
                "scenario_id": "model-selection",
                "opportunity_id": opportunity_id,
                "title": "Capability-tiered model selection",
                "estimated_saving_usd": 1.5,
            }
            with (
                patch.object(
                    optimization_agent_api,
                    "_opportunities",
                    return_value=(opportunities, 20.0, {}),
                ),
                patch.object(
                    optimization_recommendations,
                    "build_recommendations",
                    return_value=[card],
                ),
                patch.object(
                    optimization_recommendations,
                    "build_turn_metrics",
                    return_value={},
                ),
                patch.object(
                    optimization_recommendations,
                    "summarize_card_evidence",
                    return_value="evidence",
                ),
                patch.object(
                    optimization_recommendations,
                    "card_caveat",
                    return_value="caveat",
                ),
            ):
                rows = optimization_insights.build_recommendation_rows("analytics")
            recommendation = next(
                row for row in rows if row["type"] == "recommendation_card"
            )
            self.assertEqual(recommendation["estimated_saving_usd"], 1.5)
            self.assertIsNone(recommendation["opportunity_id"])

    def test_duplicate_opportunity_identity_is_rejected(self):
        opportunities = [
            {"opportunity_id": "opp-duplicate", "target": "a", "saving": 1},
            {"opportunity_id": "opp-duplicate", "target": "b", "saving": 2},
        ]
        with patch.object(
            optimization_agent_api,
            "_opportunities",
            return_value=(opportunities, 20.0, {}),
        ):
            with self.assertRaisesRegex(ValueError, "duplicate canonical opportunity_id"):
                optimization_insights.build_recommendation_rows("analytics")


if __name__ == "__main__":
    unittest.main()
