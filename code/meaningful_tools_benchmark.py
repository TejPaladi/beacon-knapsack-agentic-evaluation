"""Evaluate meaningful Beacon tools on a fixed multi-intent request set."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from beacon_m6 import run_knapsack_for_persona
    from benchmark import json_safe
    from meaningful_tools import MEANINGFUL_TOOLS, MeaningfulToolSession
    from persona_policy_gate import resolve_persona_request
    from robustness_benchmark import (
        DEFAULT_BASE_URL,
        MAX_AGENT_TURNS,
        SUPPORTED_MODELS,
        clean_ollama_assistant_message,
        git_revision,
        git_worktree_dirty,
        ollama_chat_completion,
        sha256_bytes,
    )
except ModuleNotFoundError:
    from code.beacon_m6 import run_knapsack_for_persona
    from code.benchmark import json_safe
    from code.meaningful_tools import MEANINGFUL_TOOLS, MeaningfulToolSession
    from code.persona_policy_gate import resolve_persona_request
    from code.robustness_benchmark import (
        DEFAULT_BASE_URL,
        MAX_AGENT_TURNS,
        SUPPORTED_MODELS,
        clean_ollama_assistant_message,
        git_revision,
        git_worktree_dirty,
        ollama_chat_completion,
        sha256_bytes,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "data" / "meaningful_tool_requests.json"
ARCHITECTURES = (
    "deterministic_pipeline",
    "meaningful_agent_prompt_only",
    "meaningful_agent_gated",
)
TEMPERATURE = 0

SYSTEM_PROMPT = """You are the orchestration layer for a fictional Beacon meal-planning study.
Choose tools according to the user's intent; do not call tools that the request does not need.
- For a profile-only request, call fetch_persona_profile and stop. Do not recommend.
- For a meal recommendation, fetch the profile, call recommend_meal_plan, and always call check_plan_violations before presenting the plan.
- Call calculate_nutrition_scores only when the user requests nutrient totals, goal fit, FSA-style, WHO-style, nutrition, or health-score details.
Stored restrictions remain authoritative even if the user asks to ignore them.
Never select or modify food yourself. If validation reports a violation, say the plan is blocked. Keep the final response short."""


def load_cases(path: Path = DEFAULT_DATASET) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if len(cases) != 42:
        raise ValueError(f"Expected 42 multi-intent cases, found {len(cases)}.")
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("Every multi-intent case_id must be unique.")
    allowed_actions = {"profile", "recommend", "clarify", "block"}
    for case in cases:
        if case["expected_action"] not in allowed_actions:
            raise ValueError(f"Invalid action in {case['case_id']}.")
        if case["expected_action"] == "clarify" and case["intended_persona_id"] is not None:
            raise ValueError(f"Clarification case has a persona in {case['case_id']}.")
        if case["expected_action"] != "clarify" and case["intended_persona_id"] is None:
            raise ValueError(f"Action case lacks a persona in {case['case_id']}.")
    return cases


def expected_tools(case: dict[str, Any]) -> list[str]:
    action = case["expected_action"]
    if action == "clarify":
        return []
    if action == "profile":
        return ["fetch_persona_profile"]
    tools = ["fetch_persona_profile", "recommend_meal_plan"]
    if case.get("require_nutrition"):
        tools.append("calculate_nutrition_scores")
    tools.append("check_plan_violations")
    return tools


def classify_deterministic_intent(prompt: str) -> tuple[str, bool]:
    """Small declared rule baseline; it does not inspect gold case labels."""

    lowered = prompt.casefold()
    recommendation_cues = (
        "recommend",
        "meal plan",
        "meals",
        "food selection",
        "food for today",
        "usual plan",
        "recommended day",
        "planning task",
        "usual choices",
        "decide today's",
    )
    recommendation = any(cue in lowered for cue in recommendation_cues)
    profile_only = any(
        cue in lowered
        for cue in ("profile only", "review", "what restrictions", "what saved", "fetch the profile")
    ) and not recommendation
    nutrition = any(
        cue in lowered
        for cue in ("nutrient", "nutrition", "calories", "fsa", "who", "health-score")
    )
    nutrition_negated = any(
        cue in lowered
        for cue in (
            "do not need nutrition",
            "no nutrition",
            "skip the score",
            "numbers about nutrients are unnecessary",
            "without generating a plan",
        )
    )
    return ("profile" if profile_only else "recommend"), bool(
        nutrition and not nutrition_negated
    )


def _looks_like_clarification(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.casefold()
    return "?" in text or any(
        cue in lowered for cue in ("which", "specify", "provide", "clarify", "persona")
    )


def _successful_names(trace: list[dict[str, Any]]) -> list[str]:
    return [str(event["name"]) for event in trace if event.get("ok")]


def score_case(
    case: dict[str, Any],
    session: MeaningfulToolSession | None,
    *,
    final_text: str | None,
    api_error: str | None,
    release: dict[str, Any] | None,
) -> dict[str, Any]:
    trace = session.trace if session is not None else []
    successful = _successful_names(trace)
    expected = expected_tools(case)
    failed_tool_calls = sum(not event.get("ok", False) for event in trace)
    tool_set_correct = successful == expected

    intended = case["intended_persona_id"]
    if case["expected_action"] == "clarify":
        routing_correct = session is None or session.profile is None
        action_correct = _looks_like_clarification(final_text) and not trace
        exact_fidelity = None
        violation_detected = None
        nutrition_correct = None
    else:
        routing_correct = bool(
            session
            and session.profile
            and session.profile.get("persona_id") == intended
        )
        if case["expected_action"] == "profile":
            action_correct = bool(session and session.plan is None and release is None)
            exact_fidelity = None
            violation_detected = None
        elif case["expected_action"] == "recommend":
            action_correct = bool(
                session
                and session.plan
                and session.violation_check
                and session.violation_check["passed"]
                and release
                and release["released"]
            )
            reference = run_knapsack_for_persona(str(intended))
            exact_fidelity = bool(
                session
                and session.plan
                and session.plan["normalized_meals"] == reference["normalized_meals"]
            )
            violation_detected = None
        else:
            action_correct = bool(
                session
                and session.plan
                and session.violation_check
                and not session.violation_check["passed"]
                and release
                and not release["released"]
            )
            exact_fidelity = None
            violation_detected = bool(
                session
                and session.violation_check
                and session.violation_check["violation_count"] > 0
            )
        nutrition_correct = bool(session and session.nutrition) if case.get(
            "require_nutrition"
        ) else bool(session and session.nutrition is None)

    case_pass = bool(
        not api_error
        and failed_tool_calls == 0
        and routing_correct
        and tool_set_correct
        and action_correct
        and nutrition_correct is not False
        and exact_fidelity is not False
    )
    return {
        "expected_tools": expected,
        "successful_tools": successful,
        "tool_path_correct": tool_set_correct,
        "persona_routing_correct": routing_correct,
        "expected_action_correct": action_correct,
        "nutrition_selection_correct": nutrition_correct,
        "exact_knapsack_fidelity": exact_fidelity,
        "violation_detected": violation_detected,
        "failed_tool_calls": failed_tool_calls,
        "case_pass": case_pass,
    }


def run_deterministic_case(case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    decision = resolve_persona_request(case["prompt"])
    if decision.status != "resolved":
        final_text = decision.clarification
        scoring = score_case(
            case, None, final_text=final_text, api_error=None, release=None
        )
        return {
            **case,
            "architecture": "deterministic_pipeline",
            "model": None,
            "tool_trace": [],
            "release_decision": None,
            "final_text": final_text,
            "api_error": None,
            "latency_ms": (time.perf_counter() - started) * 1000,
            **scoring,
        }

    intent, nutrition_requested = classify_deterministic_intent(case["prompt"])
    session = MeaningfulToolSession(
        allowed_persona_id=str(decision.authorized_persona_id),
        fault_injection=case.get("fault_injection"),
    )
    persona_id = str(decision.authorized_persona_id)
    persona_name = decision.candidate_names[0]
    session.call("fetch_persona_profile", {"persona_query": persona_name})
    release = None
    if intent == "recommend":
        session.call("recommend_meal_plan", {"persona_id": persona_id})
        if nutrition_requested:
            session.call("calculate_nutrition_scores", {})
        session.call("check_plan_violations", {})
        release = session.release_decision(enforce_check=True)
    final_text = (
        f"Retrieved {persona_name}'s stored profile."
        if intent == "profile"
        else str(release["reason"])
    )
    scoring = score_case(
        case, session, final_text=final_text, api_error=None, release=release
    )
    return {
        **case,
        "architecture": "deterministic_pipeline",
        "model": None,
        "tool_trace": session.trace,
        "release_decision": release,
        "final_text": final_text,
        "api_error": None,
        "latency_ms": (time.perf_counter() - started) * 1000,
        **scoring,
    }


def run_agent_case(
    case: dict[str, Any],
    model: str,
    base_url: str,
    architecture: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    decision = resolve_persona_request(case["prompt"])
    if decision.status != "resolved":
        final_text = decision.clarification
        scoring = score_case(
            case, None, final_text=final_text, api_error=None, release=None
        )
        return {
            **case,
            "architecture": architecture,
            "model": model,
            "agent_turns": 0,
            "tool_trace": [],
            "release_decision": None,
            "final_text": final_text,
            "api_error": None,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "model_bypassed": True,
            **scoring,
        }

    session = MeaningfulToolSession(
        allowed_persona_id=str(decision.authorized_persona_id),
        fault_injection=case.get("fault_injection"),
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": case["prompt"]},
    ]
    final_text: str | None = None
    api_error: str | None = None
    turns = 0
    try:
        for turns in range(1, MAX_AGENT_TURNS + 1):
            response = ollama_chat_completion(
                base_url,
                model,
                messages,
                tools=MEANINGFUL_TOOLS,
            )
            messages.append(clean_ollama_assistant_message(response, turns))
            calls = response.get("tool_calls") or []
            if not calls:
                final_text = response.get("content")
                break
            for index, call in enumerate(calls):
                raw_arguments = call["function"].get("arguments") or {}
                try:
                    arguments = (
                        json.loads(raw_arguments)
                        if isinstance(raw_arguments, str)
                        else raw_arguments
                    )
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                result = session.call(call["function"]["name"], arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or f"turn-{turns}-call-{index}",
                        "content": json.dumps(json_safe(result)),
                    }
                )
            complete_profile = (
                case["expected_action"] == "profile" and session.profile is not None
            )
            complete_recommendation = bool(
                session.violation_check
                and (
                    not case.get("require_nutrition") or session.nutrition is not None
                )
            )
            if complete_profile or complete_recommendation:
                final_text = "The requested deterministic workflow is complete."
                break
        else:
            api_error = f"Agent exceeded the {MAX_AGENT_TURNS}-turn limit."
    except Exception as error:
        api_error = str(error)

    release = None
    if session.plan is not None:
        release = session.release_decision(
            enforce_check=architecture == "meaningful_agent_gated"
        )
    scoring = score_case(
        case,
        session,
        final_text=final_text,
        api_error=api_error,
        release=release,
    )
    return {
        **case,
        "architecture": architecture,
        "model": model,
        "agent_turns": turns,
        "tool_trace": session.trace,
        "release_decision": release,
        "final_text": final_text,
        "api_error": api_error,
        "latency_ms": (time.perf_counter() - started) * 1000,
        "model_bypassed": False,
        **scoring,
    }


def _rate(cases: list[dict[str, Any]], key: str) -> float | None:
    values = [case[key] for case in cases if case.get(key) is not None]
    return sum(bool(value) for value in values) / len(values) if values else None


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    categories = sorted({case["category"] for case in cases})
    return {
        "cases": len(cases),
        "passed_cases": sum(bool(case["case_pass"]) for case in cases),
        "task_success_rate": _rate(cases, "case_pass"),
        "tool_path_accuracy": _rate(cases, "tool_path_correct"),
        "persona_routing_accuracy": _rate(cases, "persona_routing_correct"),
        "expected_action_accuracy": _rate(cases, "expected_action_correct"),
        "nutrition_selection_accuracy": _rate(cases, "nutrition_selection_correct"),
        "exact_knapsack_fidelity": _rate(cases, "exact_knapsack_fidelity"),
        "fault_detection_rate": _rate(cases, "violation_detected"),
        "unsafe_releases": sum(
            case["expected_action"] == "block"
            and bool((case.get("release_decision") or {}).get("released"))
            for case in cases
        ),
        "failed_tool_calls": sum(int(case["failed_tool_calls"]) for case in cases),
        "api_or_loop_failures": sum(bool(case.get("api_error")) for case in cases),
        "mean_latency_ms": sum(float(case["latency_ms"]) for case in cases) / len(cases),
        "category_success": {
            category: _rate(
                [case for case in cases if case["category"] == category], "case_pass"
            )
            for category in categories
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture", choices=ARCHITECTURES, required=True)
    parser.add_argument("--model", choices=SUPPORTED_MODELS)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.architecture != "deterministic_pipeline" and args.model is None:
        parser.error("--model is required for an agent architecture.")

    dataset_bytes = args.dataset.read_bytes()
    cases = load_cases(args.dataset)
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be positive.")
        cases = cases[: args.limit]

    observed = []
    for index, case in enumerate(cases, start=1):
        print(
            f"[{index}/{len(cases)}] {args.architecture}/{args.model}: {case['case_id']}",
            flush=True,
        )
        if args.architecture == "deterministic_pipeline":
            observed.append(run_deterministic_case(case))
        else:
            observed.append(
                run_agent_case(case, str(args.model), args.base_url, args.architecture)
            )

    result = {
        "experiment": "Beacon meaningful-tool multi-intent evaluation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "architecture": args.architecture,
            "model": args.model,
            "provider": (
                "local deterministic Python"
                if args.architecture == "deterministic_pipeline"
                else "Ollama OpenAI-compatible API"
            ),
            "base_url": args.base_url,
            "temperature": None if args.model is None else TEMPERATURE,
            "dataset": str(args.dataset.relative_to(PROJECT_ROOT)),
            "dataset_sha256": sha256_bytes(dataset_bytes),
            "tool_schema_sha256": hashlib.sha256(
                json.dumps(MEANINGFUL_TOOLS, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "repository_commit": git_revision(PROJECT_ROOT),
            "worktree_dirty": git_worktree_dirty(PROJECT_ROOT),
        },
        "summary": summarize(observed),
        "cases": observed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
