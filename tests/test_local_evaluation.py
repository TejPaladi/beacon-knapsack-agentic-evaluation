"""Offline tests: no API key or model call is required."""

from __future__ import annotations

import sys
import unittest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_ROOT / "code"))

from beacon_m6 import (  # noqa: E402
    endpoint_request_payload,
    evaluate_knapsack_plan,
    list_personas,
    normalized_endpoint_days,
    run_knapsack_for_persona,
)
from benchmark import (  # noqa: E402
    GROQ_USER_AGENT,
    GroqRateLimitError,
    GroqToolFormatError,
    agentic_case,
    chat_completion,
    chat_completion_with_retry,
    ToolSession,
    role_complete,
    valid_tool_sequence,
)


class LocalEvaluationTests(unittest.TestCase):
    def test_snapshot_contains_six_beacon_personas(self):
        self.assertEqual(len(list_personas()), 6)
        self.assertIn({"persona_id": "jessicaSmith", "name": "Jessica Smith"}, list_personas())

    def test_actual_knapsack_returns_a_complete_plan(self):
        plan = run_knapsack_for_persona("jessicaSmith")
        self.assertEqual(plan["algorithm"], "Beacon Knapsack")
        self.assertTrue(role_complete(plan, "jessicaSmith"))
        self.assertEqual(len(plan["meals"]), 3)

    def test_experiment_output_matches_beacons_knapsack_endpoint_for_all_personas(self):
        """Exercise Beacon's HTTP-view path without creating a user or meal plan."""

        from django.test import RequestFactory
        from core.views import recommendation_views

        factory = RequestFactory()
        with patch.object(
            recommendation_views.dataManager,
            "get_user_by_id",
            return_value=(object(), 200),
        ), patch.object(
            recommendation_views.dataManager,
            "_get_user_profile_by_id",
            return_value=None,
        ):
            for persona in list_personas():
                persona_id = persona["persona_id"]
                request = factory.post(
                    "/recommendations/knapsack",
                    data=json.dumps(endpoint_request_payload(persona_id)),
                    content_type="application/json",
                )
                response = recommendation_views.knapsack_recommendation(request)
                self.assertEqual(response.status_code, 200, persona_id)
                endpoint_plan = json.loads(response.content)
                experiment_plan = run_knapsack_for_persona(persona_id)
                self.assertEqual(
                    normalized_endpoint_days(endpoint_plan["days"]),
                    experiment_plan["normalized_meals"],
                    persona_id,
                )

    def test_knapsack_recommendation_content_is_deterministic(self):
        first = run_knapsack_for_persona("NA-V")
        second = run_knapsack_for_persona("NA-V")
        self.assertEqual(first["normalized_meals"], second["normalized_meals"])

    def test_knapsack_tool_requires_profile_lookup(self):
        session = ToolSession()
        result = session.call("run_knapsack_for_persona", {"persona_id": "jessicaSmith"})
        self.assertIn("error", result)
        session.call("get_persona", {"persona_id": "jessicaSmith"})
        plan = session.call("run_knapsack_for_persona", {"persona_id": "jessicaSmith"})
        self.assertEqual(plan["persona_id"], "jessicaSmith")

    def test_beacon_goodness_and_nutrition_goal_metrics_are_present(self):
        plan = run_knapsack_for_persona("jessicaSmith")
        evaluation = evaluate_knapsack_plan("jessicaSmith", plan)
        self.assertGreaterEqual(evaluation["legacy_goodness"]["score"], 0.0)
        self.assertLessEqual(evaluation["legacy_goodness"]["score"], 1.0)
        self.assertTrue(evaluation["quality"]["valid"])
        self.assertEqual(
            evaluation["nutrition_goal_adherence"]["mean_fit"],
            evaluation["quality"]["scores"]["nutrition_fit"],
        )
        self.assertEqual(
            set(evaluation["nutrition_goal_adherence"]["actual_totals"]),
            {"calories", "carbs", "protein", "fiber"},
        )

    def test_valid_tool_sequence_checks_persona_identity_and_order(self):
        trace = [
            {"name": "list_personas", "arguments": {}, "ok": True},
            {"name": "get_persona", "arguments": {"persona_id": "jessicaSmith"}, "ok": True},
            {"name": "run_knapsack_for_persona", "arguments": {"persona_id": "jessicaSmith"}, "ok": True},
        ]
        self.assertTrue(valid_tool_sequence(trace, "jessicaSmith"))
        self.assertFalse(valid_tool_sequence(trace, "earlJones"))

    def test_agent_loop_can_orchestrate_knapsack_with_a_mocked_model(self):
        mocked_responses = [
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {"name": "list_personas", "arguments": "{}"},
                    }
                ],
            },
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-2",
                        "function": {
                            "name": "get_persona",
                            "arguments": '{"persona_id":"jessicaSmith"}',
                        },
                    }
                ],
            },
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-3",
                        "function": {
                            "name": "run_knapsack_for_persona",
                            "arguments": '{"persona_id":"jessicaSmith"}',
                        },
                    }
                ],
            },
            {"content": "The plan is ready.", "tool_calls": []},
        ]
        with patch("benchmark.chat_completion", side_effect=mocked_responses):
            result = agentic_case("jessicaSmith", api_key="not-used", model="mock")
        self.assertIsNone(result["api_error"])
        self.assertTrue(result["tool_sequence_valid"])
        self.assertTrue(result["matches_direct_knapsack"])
        self.assertTrue(result["valid_role_coverage"])
        self.assertIn("nutrition_goal_adherence", result["quality_evaluation"])

    def test_groq_request_uses_an_explicit_user_agent(self):
        response = MagicMock()
        response.read.return_value = b'{"choices":[{"message":{"content":"ok"}}]}'
        response.__enter__.return_value = response
        with patch("benchmark.urllib.request.urlopen", return_value=response) as mocked_open:
            result = chat_completion("test-key", "test-model", [{"role": "user", "content": "hi"}])
        self.assertEqual(result["content"], "ok")
        request = mocked_open.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), GROQ_USER_AGENT)
        self.assertEqual(request.get_header("Accept"), "application/json")

    def test_rate_limit_retries_after_provider_wait(self):
        response = {"content": "ok", "tool_calls": []}
        with patch(
            "benchmark.chat_completion",
            side_effect=[GroqRateLimitError("limited", 0.0), response],
        ), patch("benchmark.time.sleep") as mocked_sleep:
            result = chat_completion_with_retry("test-key", "test-model", [], max_retries=1)
        message, retries, waited, format_retries = result
        self.assertEqual(message, response)
        self.assertEqual(retries, 1)
        self.assertEqual(waited, 1.0)
        self.assertEqual(format_retries, 0)
        mocked_sleep.assert_called_once_with(1.0)

    def test_malformed_tool_arguments_receive_a_bounded_format_retry(self):
        response = {"content": "ok", "tool_calls": []}
        messages = [{"role": "user", "content": "hi"}]
        with patch(
            "benchmark.chat_completion",
            side_effect=[GroqToolFormatError("bad JSON"), response],
        ):
            message, rate_retries, waited, format_retries = chat_completion_with_retry(
                "test-key", "test-model", messages, max_retries=1
            )
        self.assertEqual(message, response)
        self.assertEqual(rate_retries, 0)
        self.assertEqual(waited, 0.0)
        self.assertEqual(format_retries, 1)
        self.assertEqual(messages[1]["role"], "system")


if __name__ == "__main__":
    unittest.main()
