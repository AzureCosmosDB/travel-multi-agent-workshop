from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from src.app.services import optimization  # noqa: E402
from src.app import optimization_api  # noqa: E402


ACTIVE_POLICY = {
    "params": {
        "enabled": True,
        "default_deployment": "premium",
        "complexity_tiers": {
            "trivial": "nano",
            "routine": "mini",
            "complex": "premium",
        },
    }
}


class TenantScopedModelSelectionTests(unittest.TestCase):
    def test_target_tenant_uses_all_complexity_tiers(self):
        cases = (
            ("hello", ("nano", "trivial")),
            ("Find me a hotel in Paris", ("mini", "routine")),
            ("Build me a full itinerary for Paris", ("premium", "complex")),
        )
        with patch.object(optimization, "get_active_policy", return_value=ACTIVE_POLICY):
            for text, expected in cases:
                with self.subTest(text=text):
                    self.assertEqual(
                        optimization.select_deployment_for_turn(
                            [{"role": "user", "content": text}],
                            tenant_id="analytics",
                        ),
                        expected,
                    )

    def test_non_target_and_missing_tenant_fail_closed_to_default(self):
        with patch.object(optimization, "get_active_policy", return_value=None) as policy:
            self.assertEqual(
                optimization.select_deployment_for_turn(
                    [{"role": "user", "content": "hello"}],
                    tenant_id="marvel",
                ),
                (optimization.AZURE_OPENAI_DEPLOYMENT, "default"),
            )
            self.assertEqual(
                optimization.select_deployment_for_turn(
                    [{"role": "user", "content": "hello"}],
                    tenant_id=None,
                ),
                (optimization.AZURE_OPENAI_DEPLOYMENT, "default"),
            )
        policy.assert_called_once_with("model-selection", tenant_id="marvel")

    def test_no_policy_behavior_remains_default_for_target_tenant(self):
        with patch.object(optimization, "get_active_policy", return_value=None):
            self.assertEqual(
                optimization.select_deployment_for_turn(
                    [{"role": "user", "content": "hello"}],
                    tenant_id="analytics",
                ),
                (optimization.AZURE_OPENAI_DEPLOYMENT, "default"),
            )

    def test_marvel_can_enable_its_own_model_selection_policy(self):
        with patch.object(optimization, "get_active_policy", return_value=ACTIVE_POLICY):
            self.assertEqual(
                optimization.select_deployment_for_turn(
                    [{"role": "user", "content": "hello"}],
                    tenant_id="marvel",
                ),
                ("nano", "trivial"),
            )

    def test_api_telemetry_passes_route_tenant_to_selector(self):
        api_path = PYTHON_ROOT / "src" / "app" / "travel_agents_api.py"
        tree = ast.parse(api_path.read_text(encoding="utf-8"))
        tenant_values = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "select_deployment_for_turn":
                continue
            for keyword in node.keywords:
                if keyword.arg == "tenant_id" and isinstance(keyword.value, ast.Name):
                    tenant_values.append(keyword.value.id)

        self.assertTrue(
            {"tenant_id", "tenantId"}.intersection(tenant_values),
            "API telemetry selector must receive the route tenant",
        )

    def test_live_policy_list_is_tenant_scoped(self):
        policies = [
            {"scenario": "model-selection", "status": "active"},
            {"scenario": "active-trip-city-context", "status": "active"},
            {"scenario": "memory-retention", "status": "reverted"},
        ]
        with patch.object(optimization_api.optimization_policy, "list_policies", return_value=policies):
            marvel = optimization_api.list_policies("marvel")["policies"]
            analytics = optimization_api.list_policies("analytics")["policies"]

        self.assertEqual([p["scenario"] for p in marvel], ["memory-retention"])
        self.assertEqual(
            [p["scenario"] for p in analytics],
            ["model-selection", "memory-retention"],
        )

    def test_apply_uses_route_tenant_policy(self):
        with (
            patch.object(
                optimization_api._LIFECYCLE_COORDINATOR,
                "acquire",
                return_value=object(),
            ),
            patch.object(
                optimization_api._LIFECYCLE_COORDINATOR,
                "release",
                return_value=True,
            ),
            patch.object(optimization_api.optimization_policy, "get_policy", return_value={}),
            patch.object(
                optimization_api.optimization_policy,
                "apply_policy",
                return_value={"status": "active"},
            ) as apply_policy,
        ):
            optimization_api.apply(
                "model-selection",
                optimization_api.ActionBody(by="test", tenant_id="marvel"),
            )
        apply_policy.assert_called_once_with(
            "model-selection",
            by="test",
            tenant_id="marvel",
        )


if __name__ == "__main__":
    unittest.main()
