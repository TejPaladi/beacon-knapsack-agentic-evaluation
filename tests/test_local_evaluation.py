"""Offline tests: no API key or model call is required."""

from __future__ import annotations

import sys
import unittest
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_ROOT / "code"))

from beacon_m6 import (  # noqa: E402
    calculate_plan_health_scores,
    check_plan_violations,
    endpoint_request_payload,
    evaluate_knapsack_plan,
    list_personas,
    normalized_endpoint_days,
    run_knapsack_for_persona,
)
from meaningful_tools import (  # noqa: E402
    MEANINGFUL_TOOLS,
    MeaningfulToolSession,
    resolve_profile_query,
)
from meaningful_tools_benchmark import (  # noqa: E402
    HELDOUT_DATASET,
    expected_tools as meaningful_expected_tools,
    is_text_tool_call,
    load_cases as load_meaningful_cases,
    reply_state_flags,
    run_agent_case as run_meaningful_agent_case,
    run_deterministic_case as run_meaningful_deterministic_case,
    valid_tool_path,
)
from report_meaningful_tools import paraphrase_pairs  # noqa: E402
from rule_persona_resolver import resolve as resolve_rules  # noqa: E402
from hard_wording_benchmark import (  # noqa: E402
    load_cases as load_hard_cases,
    parse_answer,
    run_case as run_hard_case,
    score as score_hard,
)
from report_hard_wording import full_name_persona  # noqa: E402
from rule_reranker import choose as rerank_with_rules, detect as detect_preference  # noqa: E402
from end_to_end_benchmark import identify as identify_methods, outcome as end_to_end_outcome  # noqa: E402
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
    def test_tool_path_allows_independent_nutrition_and_check_order(self):
        expected = [
            "fetch_persona_profile",
            "recommend_meal_plan",
            "calculate_nutrition_scores",
            "check_plan_violations",
        ]
        self.assertTrue(valid_tool_path(expected, expected))
        self.assertTrue(
            valid_tool_path(
                [
                    "fetch_persona_profile",
                    "recommend_meal_plan",
                    "check_plan_violations",
                    "calculate_nutrition_scores",
                ],
                expected,
            )
        )
        self.assertFalse(valid_tool_path(expected[:-1], expected))

    def test_tool_path_requires_release_after_validation(self):
        expected = [
            "fetch_persona_profile",
            "recommend_meal_plan",
            "check_plan_violations",
            "release_plan",
        ]
        self.assertTrue(valid_tool_path(expected, expected))
        self.assertFalse(
            valid_tool_path(
                [
                    "fetch_persona_profile",
                    "recommend_meal_plan",
                    "release_plan",
                    "check_plan_violations",
                ],
                expected,
            )
        )

    def test_meaningful_tool_schema_has_four_capabilities_and_release(self):
        names = [tool["function"]["name"] for tool in MEANINGFUL_TOOLS]
        self.assertEqual(
            names,
            [
                "fetch_persona_profile",
                "recommend_meal_plan",
                "calculate_nutrition_scores",
                "check_plan_violations",
                "release_plan",
            ],
        )

    def test_combined_profile_tool_resolves_id_full_and_first_name(self):
        self.assertEqual(resolve_profile_query("jessicaSmith")["persona_id"], "jessicaSmith")
        self.assertEqual(resolve_profile_query("Jessica Smith")["persona_id"], "jessicaSmith")
        self.assertEqual(resolve_profile_query("Jessica")["persona_id"], "jessicaSmith")
        with self.assertRaises(ValueError):
            resolve_profile_query("Priya")

    def test_meaningful_tools_enforce_dependencies_and_optional_nutrition(self):
        session = MeaningfulToolSession(allowed_persona_id="jessicaSmith")
        early = session.call("recommend_meal_plan", {"persona_id": "jessicaSmith"})
        self.assertIn("error", early)
        profile = session.call(
            "fetch_persona_profile", {"persona_query": "Jessica Smith"}
        )
        self.assertEqual(profile["persona_id"], "jessicaSmith")
        plan = session.call("recommend_meal_plan", {"persona_id": "jessicaSmith"})
        self.assertEqual(plan["persona_id"], "jessicaSmith")
        nutrition = session.call("calculate_nutrition_scores", {})
        self.assertIn("fsa_style_proxy", nutrition)
        check = session.call("check_plan_violations", {})
        self.assertTrue(check["passed"])
        self.assertTrue(session.call("release_plan", {})["released"])
        self.assertEqual(session.release_decision()["status"], "released")

    def test_nutrition_tool_reports_proxy_coverage_and_goal_fit(self):
        plan = run_knapsack_for_persona("earlJones")
        analysis = calculate_plan_health_scores("earlJones", plan)
        self.assertEqual(analysis["item_count"], 9)
        self.assertIn("mean_fit", analysis["goal_fit"])
        for key in ("fsa_style_proxy", "who_style_proxy"):
            self.assertGreaterEqual(analysis[key]["coverage"], 0.0)
            self.assertLessEqual(analysis[key]["coverage"], 1.0)
            self.assertEqual(analysis[key]["total_items"], 9)
        self.assertIn("proxy", analysis["scope_note"].lower())

    def test_violation_checker_and_release_gate_block_injected_missing_role(self):
        reference = run_knapsack_for_persona("jessicaSmith")
        corrupted = deepcopy(reference)
        corrupted["meals"][0]["items"] = corrupted["meals"][0]["items"][1:]
        check = check_plan_violations("jessicaSmith", corrupted)
        self.assertFalse(check["passed"])
        self.assertTrue(any(item["type"] == "missing_role" for item in check["violations"]))

        for enforce, released in ((True, False), (False, True)):
            session = MeaningfulToolSession(
                allowed_persona_id="jessicaSmith",
                fault_injection="remove_first_role",
                enforce_release_check=enforce,
            )
            session.call("fetch_persona_profile", {"persona_query": "Jessica Smith"})
            session.call("recommend_meal_plan", {"persona_id": "jessicaSmith"})
            session.call("check_plan_violations", {})
            session.call("release_plan", {})
            self.assertEqual(session.released, released)
            self.assertEqual(session.trace[-1].get("policy_blocked", False), enforce)

    def test_release_gate_refuses_unchecked_release(self):
        session = MeaningfulToolSession(allowed_persona_id="jessicaSmith")
        session.call("fetch_persona_profile", {"persona_query": "Jessica Smith"})
        session.call("recommend_meal_plan", {"persona_id": "jessicaSmith"})
        self.assertIn("error", session.call("release_plan", {}))
        self.assertEqual(session.release_decision()["status"], "blocked_by_gate")

    def test_meaningful_dataset_has_fixed_balanced_design(self):
        cases = load_meaningful_cases()
        counts = {}
        for case in cases:
            counts[case["category"]] = counts.get(case["category"], 0) + 1
        self.assertEqual(len(cases), 42)
        self.assertEqual(set(counts.values()), {6})
        nutrition_case = next(case for case in cases if case["case_id"] == "nutrition_earl")
        self.assertEqual(
            meaningful_expected_tools(nutrition_case),
            [
                "fetch_persona_profile",
                "recommend_meal_plan",
                "calculate_nutrition_scores",
                "check_plan_violations",
                "release_plan",
            ],
        )
        fault_case = next(case for case in cases if case["case_id"] == "fault_earl")
        self.assertNotIn("release_plan", meaningful_expected_tools(fault_case))

    def test_heldout_dataset_matches_design_with_new_wording(self):
        development = load_meaningful_cases()
        heldout = load_meaningful_cases(HELDOUT_DATASET)

        def design(cases):
            return sorted(
                (
                    case["category"],
                    case["expected_action"],
                    case["intended_persona_id"] or "",
                    bool(case["require_nutrition"]),
                    case.get("fault_injection") or "",
                )
                for case in cases
            )

        self.assertEqual(design(heldout), design(development))
        self.assertFalse(
            {case["prompt"] for case in heldout} & {case["prompt"] for case in development}
        )
        for case in heldout:
            decision = resolve_persona_request(case["prompt"])
            if case["expected_action"] == "clarify":
                self.assertNotEqual(decision.status, "resolved", case["case_id"])
            else:
                self.assertEqual(
                    decision.authorized_persona_id,
                    case["intended_persona_id"],
                    case["case_id"],
                )

    def scripted_model(self, replies, seen_messages):
        """Return queued assistant messages and record what the model saw."""

        queue = list(replies)

        def reply(base_url, model, messages, **options):
            seen_messages.append(deepcopy(messages))
            return queue.pop(0)

        return reply

    @staticmethod
    def tool_call(name, arguments=None):
        return {
            "content": None,
            "tool_calls": [
                {"function": {"name": name, "arguments": arguments or {}}}
            ],
        }

    def test_agent_loop_does_not_stop_on_case_labels(self):
        case = {
            "case_id": "profile_label_check",
            "category": "profile_only",
            "prompt": "Show the saved dietary profile for Earl Jones.",
            "intended_persona_id": "earlJones",
            "expected_action": "profile",
            "require_nutrition": False,
        }
        replies = [
            self.tool_call("fetch_persona_profile", {"persona_query": "Earl Jones"}),
            self.tool_call("recommend_meal_plan", {"persona_id": "earlJones"}),
            {"content": "Done.", "tool_calls": []},
        ]
        seen = []
        with patch(
            "meaningful_tools_benchmark.ollama_chat_completion",
            side_effect=self.scripted_model(replies, seen),
        ):
            result = run_meaningful_agent_case(
                case, "granite4:3b", "http://localhost:11434/v1", "meaningful_agent_gated"
            )
        self.assertEqual(len(seen), 3)
        self.assertIn("recommend_meal_plan", result["successful_tools"])
        self.assertFalse(result["case_pass"])
        self.assertFalse(result["outcome_correct"])

    def run_scripted_fault_case(self, architecture):
        case = {
            "case_id": "fault_scripted",
            "category": "fault_injection",
            "prompt": "Recommend a plan for Jessica Smith.",
            "intended_persona_id": "jessicaSmith",
            "expected_action": "block",
            "require_nutrition": False,
            "fault_injection": "remove_first_role",
        }
        replies = [
            self.tool_call("fetch_persona_profile", {"persona_query": "Jessica Smith"}),
            self.tool_call("recommend_meal_plan", {"persona_id": "jessicaSmith"}),
            self.tool_call("check_plan_violations"),
            self.tool_call("release_plan"),
            {"content": "Here is the plan.", "tool_calls": []},
        ]
        seen = []
        with patch(
            "meaningful_tools_benchmark.ollama_chat_completion",
            side_effect=self.scripted_model(replies, seen),
        ):
            result = run_meaningful_agent_case(
                case, "granite4:3b", "http://localhost:11434/v1", architecture
            )
        return result, seen

    def test_model_sees_failed_validation_before_its_release_decision(self):
        result, seen = self.run_scripted_fault_case("meaningful_agent_prompt_only")
        check_message = json.loads(seen[3][-1]["content"])
        self.assertFalse(check_message["passed"])
        self.assertTrue(result["released"])
        self.assertTrue(result["unsafe_release"])
        self.assertFalse(result["outcome_correct"])
        self.assertFalse(result["case_pass"])

    def test_release_gate_contains_unsafe_release_but_not_model_error(self):
        result, _ = self.run_scripted_fault_case("meaningful_agent_gated")
        self.assertFalse(result["released"])
        self.assertFalse(result["unsafe_release"])
        self.assertEqual(result["release_blocks"], 1)
        self.assertTrue(result["outcome_correct"])
        self.assertFalse(result["case_pass"])

    def test_deterministic_pipeline_releases_only_validated_plans(self):
        cases = {case["case_id"]: case for case in load_meaningful_cases()}
        safe = run_meaningful_deterministic_case(cases["recommend_earl"])
        fault = run_meaningful_deterministic_case(cases["fault_earl"])
        self.assertTrue(safe["case_pass"])
        self.assertEqual(safe["release_decision"]["status"], "released")
        self.assertTrue(fault["case_pass"])
        self.assertFalse(fault["released"])

    def test_rule_resolver_handles_names_nicknames_typos_and_conflicts(self):
        def who(*turns):
            messages = [
                {"role": "user" if i % 2 == 0 else "assistant", "content": text}
                for i, text in enumerate(turns)
            ]
            return resolve_rules(messages).persona_id

        self.assertEqual(who("Plan meals for Greg Taylor."), "NA-NV")
        self.assertEqual(who("plan meals for jess smith"), "jessicaSmith")
        self.assertEqual(who("Rebecca needs a menu."), "NA-V")
        self.assertEqual(who("Make a plan for Jesicca."), "jessicaSmith")
        self.assertIsNone(who("Make a plan for Greg Thompson."))
        self.assertIsNone(who("Make a plan for Jessica Jones."))
        self.assertIsNone(who("More protein for lunch, please."))
        self.assertIsNone(who("An early dinner plan, please."))
        self.assertEqual(who("Dr. Brooks wants her plan."), "A-NV")
        self.assertEqual(who("Plan meals for E.J. today."), "earlJones")

    def test_rule_resolver_uses_attributes_corrections_and_earlier_turns(self):
        def who(*turns):
            messages = [
                {"role": "user" if i % 2 == 0 else "assistant", "content": text}
                for i, text in enumerate(turns)
            ]
            return resolve_rules(messages).persona_id

        self.assertEqual(who("Plan meals for the diabetic client."), "jessicaSmith")
        self.assertIsNone(who("Plan meals for the vegetarian client."))
        self.assertIsNone(who("Plan meals for the vegan client."))
        self.assertEqual(who("Plan for the 2,400 calorie client."), "earlJones")
        self.assertEqual(who("Plan for Greg. Sorry, I meant Dylan."), "A-V")
        self.assertEqual(who("Use Dylan, not Greg."), "A-V")
        self.assertEqual(
            who("I look after Earl Jones and Becca Moore.", "Noted.", "Do the vegetarian one."),
            "NA-V",
        )
        self.assertEqual(
            who("I look after Earl Jones and Becca Moore.", "Noted.", "Start with the second one."),
            "NA-V",
        )
        self.assertEqual(who("I work with Aaliyah Brooks.", "Okay.", "Plan her meals."), "A-NV")
        self.assertIsNone(who("Plan her meals for today."))

    def test_hard_wording_dataset_has_balanced_labeled_design(self):
        cases = load_hard_cases()
        by_category = {}
        for case in cases:
            by_category.setdefault(case["category"], []).append(case)
        self.assertEqual(len(by_category), 8)
        self.assertTrue(all(len(group) == 6 for group in by_category.values()))
        resolvable = [c for c in cases if c["expected_action"] == "resolve"]
        self.assertEqual(len(resolvable), 36)
        personas = {}
        for case in resolvable:
            personas[case["expected_persona_id"]] = personas.get(case["expected_persona_id"], 0) + 1
        self.assertEqual(set(personas.values()), {6})

    def test_hard_wording_scoring_separates_wrong_person_from_missed(self):
        resolvable = {"expected_persona_id": "NA-V"}
        clarify = {"expected_persona_id": None}
        self.assertEqual(score_hard(resolvable, "NA-V")["outcome"], "correct_resolution")
        self.assertEqual(score_hard(resolvable, None)["outcome"], "missed_resolution")
        self.assertTrue(score_hard(resolvable, "A-V")["wrong_person"])
        self.assertTrue(score_hard(clarify, "NA-NV")["wrong_person"])
        self.assertTrue(score_hard(clarify, None)["correct_action"])
        self.assertEqual(parse_answer('{"persona_id": "unclear"}'), "unclear")
        self.assertIsNone(parse_answer('{"persona_id": "Becca"}'))
        self.assertIsNone(parse_answer("not json"))

    def test_hard_wording_model_resolver_treats_unclear_as_clarification(self):
        case = next(c for c in load_hard_cases() if c["case_id"] == "near_greg")
        reply = {"content": '{"persona_id": "unclear"}', "done_reason": "stop",
                 "prompt_tokens": 10, "completion_tokens": 5}
        with patch("hard_wording_benchmark.call_model", return_value=reply):
            result = run_hard_case(case, "model", "granite4:3b", "http://localhost:11434/v1")
        self.assertEqual(result["outcome"], "correct_clarification")
        reply["content"] = '{"persona_id": "NA-NV"}'
        with patch("hard_wording_benchmark.call_model", return_value=reply):
            result = run_hard_case(case, "model", "granite4:3b", "http://localhost:11434/v1")
        self.assertTrue(result["wrong_person"])

    def test_propose_and_confirm_executes_only_a_single_stored_full_name(self):
        def turns(*texts):
            return [{"role": "user", "content": text} for text in texts]

        self.assertEqual(full_name_persona(turns("Plan meals for Becca Moore.")), "NA-V")
        self.assertIsNone(full_name_persona(turns("Plan for Becca Moore or Greg Taylor.")))
        self.assertIsNone(full_name_persona(turns("Plan for Becca.")))
        self.assertEqual(
            full_name_persona(turns("Plan for Greg Taylor.", "I meant Aaliyah Brooks, not Greg.")),
            "A-NV",
        )

    def test_rule_reranker_detects_nutrient_and_direction(self):
        self.assertEqual(detect_preference("Give me the plan with more protein."), ("protein", 1))
        self.assertEqual(detect_preference("I want fewer calories today."), ("kcal", -1))
        self.assertEqual(detect_preference("I am trying to gain weight."), ("kcal", 1))
        self.assertEqual(detect_preference("I'm trying to lose weight."), ("kcal", -1))
        self.assertEqual(detect_preference("Please keep the carbs low."), ("carbs", -1))
        self.assertEqual(detect_preference("High fibre, please."), ("fiber", 1))
        self.assertIsNone(detect_preference("Surprise me today."))

    def test_rule_reranker_picks_best_candidate_or_default(self):
        candidates = [
            {"number": 1, "totals": {"kcal": 2000, "carbs": 300, "protein": 60, "fiber": 20}},
            {"number": 2, "totals": {"kcal": 1800, "carbs": 250, "protein": 80, "fiber": 20}},
            {"number": 3, "totals": {"kcal": 2200, "carbs": 350, "protein": 50, "fiber": 30}},
        ]
        self.assertEqual(rerank_with_rules("More protein please.", candidates), 2)
        self.assertEqual(rerank_with_rules("Lowest calories.", candidates), 2)
        self.assertEqual(rerank_with_rules("Lots of fiber.", candidates), 3)
        self.assertEqual(rerank_with_rules("Anything is fine.", candidates), 1)

    def test_propose_confirm_only_proceeds_with_a_confirmed_or_fully_named_person(self):
        cases = {c["case_id"]: c for c in load_hard_cases()}
        near = identify_methods(cases["near_greg"], "NA-NV")
        self.assertEqual(near["model_decides"]["persona_id"], "NA-NV")
        self.assertIsNone(near["propose_confirm"]["persona_id"])
        self.assertTrue(near["propose_confirm"]["confirmation_asked"])
        self.assertIsNone(near["stronger_rules"]["persona_id"])
        typo = identify_methods(cases["typo_becca"], "NA-V")
        self.assertEqual(typo["propose_confirm"]["persona_id"], "NA-V")
        exact = identify_methods(cases["exact_greg"], "unclear")
        self.assertEqual(exact["propose_confirm"]["persona_id"], "NA-NV")
        self.assertFalse(exact["propose_confirm"]["confirmation_asked"])

    def test_end_to_end_outcome_separates_wrong_release_from_workflow_failure(self):
        resolvable = {"expected_persona_id": "NA-V"}
        clarify = {"expected_persona_id": None}
        released = {"released": True, "released_plan_valid": True}
        withheld = {"released": False, "released_plan_valid": False}
        self.assertEqual(end_to_end_outcome(resolvable, "NA-V", released), "right_plan")
        self.assertEqual(end_to_end_outcome(resolvable, "A-V", released), "wrong_person_release")
        self.assertEqual(end_to_end_outcome(resolvable, "NA-V", withheld), "identified_not_delivered")
        self.assertEqual(end_to_end_outcome(resolvable, None, None), "missed")
        self.assertEqual(end_to_end_outcome(clarify, None, None), "correct_clarification")
        self.assertEqual(end_to_end_outcome(clarify, "NA-NV", released), "wrong_person_release")

    def test_text_tool_call_detector_accepts_malformed_calls_to_known_tools(self):
        self.assertTrue(
            is_text_tool_call('{"name": "calculate_nutrition_scores", "parameters": {"goals": {"fiber": 28}}')
        )
        self.assertTrue(is_text_tool_call('```json\n{"name": "release_plan"}\n```'))
        self.assertFalse(is_text_tool_call('{"name": "Earl Jones"}'))
        self.assertFalse(is_text_tool_call("Here is the plan."))

    def test_reply_checks_flag_claims_that_contradict_recorded_state(self):
        failed_check = {
            "name": "check_plan_violations",
            "ok": True,
            "outcome": {"passed": False, "violation_count": 1},
        }
        released_fault = {
            "expected_action": "block",
            "tool_trace": [failed_check],
            "released": True,
            "release_decision": {"status": "released_unchecked"},
        }
        flags = reply_state_flags(
            {**released_fault, "final_text": "The plan has been successfully validated and released."}
        )
        self.assertIn("validation_claim", flags)
        flags = reply_state_flags(
            {**released_fault, "final_text": "The plan fails validation, so it cannot be released."}
        )
        self.assertEqual(set(flags), {"release_claim"})
        advice = "Please validate the plan to ensure it meets all the requirements."
        self.assertEqual(reply_state_flags({**released_fault, "final_text": advice}), {})
        invented = {
            "expected_action": "recommend",
            "tool_trace": [],
            "released": False,
            "release_decision": {"status": "no_plan"},
            "final_text": "Here is a plan.\nBreakfast: oats\nLunch: salad\nDinner: salmon",
        }
        self.assertIn("plan_without_knapsack", reply_state_flags(invented))
        self.assertEqual(reply_state_flags({**invented, "model_bypassed": True}), {})

    def test_heldout_paraphrases_pair_with_every_model_handled_case(self):
        development = load_meaningful_cases()
        heldout = load_meaningful_cases(HELDOUT_DATASET)
        pairs = paraphrase_pairs(development, heldout)
        self.assertEqual(len(pairs), 36)
        self.assertTrue(all(held == "heldout_" + dev for dev, held in pairs))
        broken = deepcopy(heldout)
        broken[0]["expected_action"] = "recommend"
        with self.assertRaises(ValueError):
            paraphrase_pairs(development, broken)

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
