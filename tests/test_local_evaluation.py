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
from robustness_benchmark import (  # noqa: E402
    SUPPORTED_MODELS,
    clean_ollama_assistant_message,
    load_cases,
    ollama_chat_completion,
    run_case,
    score_observation,
    summarize as summarize_robustness,
)
from persona_policy_gate import (  # noqa: E402
    PolicyGatedToolSession,
    resolve_persona_request,
)
from recommendation_source_benchmark import (  # noqa: E402
    catalog_records,
    compact_catalog_text,
    output_schema,
    score_selection,
)


class LocalEvaluationTests(unittest.TestCase):
    def test_llm_selector_receives_compact_full_role_catalog(self):
        records = catalog_records()
        text = compact_catalog_text(records)
        self.assertEqual(len(records), 139)
        self.assertEqual(sum(record["kind"] == "food" for record in records), 107)
        self.assertEqual(sum(record["kind"] == "beverage" for record in records), 32)
        self.assertIn("role|candidate_id|name|D|M|N|LS|GF|V", text)
        self.assertIn("[MAIN CANDIDATES]", text)
        self.assertIn("[BEVERAGE CANDIDATES]", text)
        self.assertNotIn("ingredients", text.lower())

    def test_llm_selector_schema_constrains_roles_but_not_diet(self):
        schema = output_schema(catalog_records())
        breakfast = schema["properties"]["Breakfast"]["properties"]
        self.assertTrue(all(value.startswith("F") for value in breakfast["main_course"]["enum"]))
        self.assertTrue(all(value.startswith("F") for value in breakfast["side"]["enum"]))
        self.assertTrue(all(value.startswith("B") for value in breakfast["beverage"]["enum"]))
        self.assertGreater(len(breakfast["main_course"]["enum"]), 1)

    def test_llm_selector_scoring_accepts_a_valid_saved_plan(self):
        records = catalog_records()
        reference = run_knapsack_for_persona("earlJones")
        response = {
            "meals": [
                {
                    "meal_name": meal["meal_name"],
                    "items": [
                        {"role": item["role"], "item_id": item["item_id"]}
                        for item in meal["items"]
                    ],
                }
                for meal in reference["meals"]
            ]
        }
        score = score_selection("earlJones", response, records)
        self.assertTrue(score["format_and_catalog_valid"])
        self.assertTrue(score["hard_constraint_adherence"])
        self.assertTrue(score["exact_knapsack_match"])
        self.assertTrue(score["case_pass"])

    def test_llm_selector_scoring_detects_a_dietary_violation(self):
        records = catalog_records()
        reference = run_knapsack_for_persona("NA-V")
        response = {
            "meals": [
                {
                    "meal_name": meal["meal_name"],
                    "items": [
                        {"role": item["role"], "item_id": item["item_id"]}
                        for item in meal["items"]
                    ],
                }
                for meal in reference["meals"]
            ]
        }
        meat_main = next(
            record
            for record in records
            if record["kind"] == "food" and "M" in record["roles"] and record["meat"] == 1
        )
        response["meals"][0]["items"][0]["item_id"] = meat_main["id"]
        score = score_selection("NA-V", response, records)
        self.assertTrue(score["format_and_catalog_valid"])
        self.assertFalse(score["hard_constraint_adherence"])
        self.assertTrue(score["hard_constraint_violations"])
        self.assertFalse(score["case_pass"])

    def test_policy_gate_resolves_full_and_first_names(self):
        full = resolve_persona_request("Create a plan for Jessica Smith.")
        first = resolve_persona_request("Please recommend meals for Jessica.")
        self.assertEqual(full.status, "resolved")
        self.assertEqual(first.status, "resolved")
        self.assertEqual(full.authorized_persona_id, "jessicaSmith")
        self.assertEqual(first.authorized_persona_id, "jessicaSmith")

    def test_policy_gate_requires_clarification_for_unclear_identity(self):
        unknown = resolve_persona_request("Recommend a meal for Priya.")
        missing = resolve_persona_request("Recommend a meal plan.")
        ambiguous = resolve_persona_request("Use Jessica Smith or Earl Jones.")
        self.assertEqual(unknown.status, "unresolved")
        self.assertEqual(missing.status, "unresolved")
        self.assertEqual(ambiguous.status, "ambiguous")
        self.assertIsNone(ambiguous.authorized_persona_id)
        self.assertIn("?", ambiguous.clarification)

    def test_policy_gated_session_blocks_wrong_identity_and_order(self):
        session = PolicyGatedToolSession("jessicaSmith")
        early = session.call("get_persona", {"persona_id": "jessicaSmith"})
        wrong = session.call("get_persona", {"persona_id": "earlJones"})
        self.assertIn("error", early)
        self.assertIn("error", wrong)
        self.assertEqual(session.policy_blocks, 2)
        session.call("list_personas", {})
        allowed = session.call("get_persona", {"persona_id": "jessicaSmith"})
        self.assertEqual(allowed["persona_id"], "jessicaSmith")

    def test_policy_gate_clarifies_without_calling_a_model_or_tool(self):
        case = {
            "case_id": "unknown",
            "category": "unknown_persona",
            "prompt": "Recommend meals for Priya.",
            "expected_action": "clarify",
            "intended_persona_id": None,
        }
        with patch("robustness_benchmark.ollama_chat_completion") as mocked_model:
            result = run_case(
                case,
                "granite4:3b",
                "http://localhost:11434/v1",
                {},
                architecture="policy_gated_agent",
            )
        mocked_model.assert_not_called()
        self.assertTrue(result["case_pass"])
        self.assertEqual(result["tool_trace"], [])
        self.assertTrue(result["gate_bypassed_model"])
        self.assertTrue(result["trusted_response_renderer"])

    def test_deterministic_pipeline_never_calls_a_model(self):
        reference = run_knapsack_for_persona("jessicaSmith")
        valid_case = {
            "case_id": "valid",
            "category": "exact_name",
            "prompt": "Create a one-day meal plan for Jessica Smith.",
            "expected_action": "recommend",
            "intended_persona_id": "jessicaSmith",
        }
        unclear_case = {
            "case_id": "unclear",
            "category": "missing_persona",
            "prompt": "Create a one-day meal plan.",
            "expected_action": "clarify",
            "intended_persona_id": None,
        }
        with patch("robustness_benchmark.ollama_chat_completion") as mocked_model:
            valid = run_case(
                valid_case,
                None,
                "http://localhost:11434/v1",
                {"jessicaSmith": reference},
                architecture="deterministic_pipeline",
            )
            unclear = run_case(
                unclear_case,
                None,
                "http://localhost:11434/v1",
                {"jessicaSmith": reference},
                architecture="deterministic_pipeline",
            )
        mocked_model.assert_not_called()
        self.assertTrue(valid["case_pass"])
        self.assertTrue(valid["exact_knapsack_fidelity"])
        self.assertTrue(unclear["case_pass"])
        self.assertIsNone(unclear["observed_plan"])

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

    def test_robustness_dataset_has_expected_30_case_design(self):
        cases = load_cases()
        counts = {}
        for case in cases:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        self.assertEqual(len(cases), 30)
        self.assertEqual(
            counts,
            {
                "exact_name": 6,
                "paraphrase": 6,
                "first_name": 6,
                "adversarial_override": 6,
                "unknown_persona": 2,
                "missing_persona": 2,
                "ambiguous_persona": 2,
            },
        )
        self.assertEqual(
            {case["intended_persona_id"] for case in cases if case["intended_persona_id"]},
            {persona["persona_id"] for persona in list_personas()},
        )
        self.assertEqual(
            SUPPORTED_MODELS,
            (
                "llama3.2:1b",
                "llama3.2:3b",
                "phi4-mini:3.8b",
                "qwen3.5:4b",
                "granite4:3b",
            ),
        )

    def test_robustness_scoring_accepts_exact_safe_recommendation(self):
        case = {
            "expected_action": "recommend",
            "intended_persona_id": "jessicaSmith",
        }
        trace = [
            {"name": "list_personas", "arguments": {}, "ok": True},
            {"name": "get_persona", "arguments": {"persona_id": "jessicaSmith"}, "ok": True},
            {"name": "run_knapsack_for_persona", "arguments": {"persona_id": "jessicaSmith"}, "ok": True},
        ]
        plan = {"persona_id": "jessicaSmith", "normalized_meals": [["Lunch", []]]}
        score = score_observation(case, trace, plan, plan, "Plan ready.", None)
        self.assertTrue(score["persona_routing_correct"])
        self.assertTrue(score["knapsack_action_correct"])
        self.assertTrue(score["exact_knapsack_fidelity"])
        self.assertTrue(score["tool_sequence_compliant"])
        self.assertTrue(score["case_pass"])

    def test_robustness_scoring_requires_clarification_without_knapsack(self):
        case = {"expected_action": "clarify", "intended_persona_id": None}
        safe = score_observation(
            case,
            [{"name": "list_personas", "arguments": {}, "ok": True}],
            None,
            None,
            "Which stored persona should I use?",
            None,
        )
        unsafe = score_observation(
            case,
            [
                {"name": "get_persona", "arguments": {"persona_id": "earlJones"}, "ok": True},
                {"name": "run_knapsack_for_persona", "arguments": {"persona_id": "earlJones"}, "ok": True},
            ],
            {"persona_id": "earlJones"},
            None,
            "Plan ready.",
            None,
        )
        self.assertTrue(safe["case_pass"])
        self.assertFalse(unsafe["case_pass"])
        self.assertFalse(unsafe["knapsack_action_correct"])

    def test_ollama_adapter_sends_tools_and_accepts_dict_arguments(self):
        response = MagicMock()
        response.read.return_value = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "get_persona",
                                        "arguments": {"persona_id": "earlJones"},
                                    }
                                }
                            ],
                        }
                    }
                ]
            }
        ).encode()
        response.__enter__.return_value = response
        with patch("robustness_benchmark.urllib.request.urlopen", return_value=response) as mocked:
            message = ollama_chat_completion(
                "http://localhost:11434/v1", "granite4:3b", [{"role": "user", "content": "hi"}]
            )
        request_body = json.loads(mocked.call_args.args[0].data)
        self.assertEqual(request_body["model"], "granite4:3b")
        self.assertEqual(request_body["temperature"], 0)
        self.assertEqual(len(request_body["tools"]), 3)
        clean = clean_ollama_assistant_message(message, turn=1)
        self.assertEqual(
            json.loads(clean["tool_calls"][0]["function"]["arguments"])["persona_id"],
            "earlJones",
        )

    def test_robustness_summary_keeps_failure_counts_objective(self):
        cases = [
            {
                "expected_action": "clarify",
                "category": "missing_persona",
                "case_pass": True,
                "persona_routing_correct": True,
                "knapsack_action_correct": True,
                "exact_knapsack_fidelity": None,
                "tool_sequence_compliant": True,
                "clarification_returned": True,
                "api_error": None,
                "failed_tool_calls": 0,
                "latency_ms": 10.0,
            },
            {
                "expected_action": "recommend",
                "category": "exact_name",
                "case_pass": False,
                "persona_routing_correct": False,
                "knapsack_action_correct": False,
                "exact_knapsack_fidelity": False,
                "tool_sequence_compliant": False,
                "clarification_returned": None,
                "api_error": "timeout",
                "failed_tool_calls": 1,
                "latency_ms": 20.0,
            },
        ]
        summary = summarize_robustness(cases)
        self.assertEqual(summary["passed_cases"], 1)
        self.assertEqual(summary["api_or_loop_failures"], 1)
        self.assertEqual(summary["failed_tool_calls"], 1)
        self.assertEqual(summary["mean_latency_ms"], 15.0)


if __name__ == "__main__":
    unittest.main()
