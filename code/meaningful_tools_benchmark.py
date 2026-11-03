"""Evaluate meaningful Beacon tools on a fixed multi-intent request set.

The agent loop never reads case labels. A resolved request runs until the
model answers without a tool call or reaches the turn limit, and every tool
result, including a failed validation, is returned to the model before it
decides what to do next. Labels are used only for scoring after the loop ends.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from beacon_m6 import beacon_backend_path, check_plan_violations, run_knapsack_for_persona
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
    from code.beacon_m6 import (
        beacon_backend_path,
        check_plan_violations,
        run_knapsack_for_persona,
    )
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
HELDOUT_DATASET = PROJECT_ROOT / "data" / "meaningful_tool_requests_heldout.json"
ARCHITECTURES = (
    "deterministic_pipeline",
    "meaningful_agent_prompt_only",
    "meaningful_agent_gated",
)
TEMPERATURE = 0
# Large enough that Qwen 3.5's reasoning does not exhaust the budget before it
# answers; the earlier 160-token cap truncated it to empty replies.
MAX_COMPLETION_TOKENS = 1024
STOP_RULE = (
    "model returns a message without tool calls, or the turn limit is reached; "
    "case labels are not read during the loop"
)

SYSTEM_PROMPT = """You are the orchestration layer for a fictional Beacon meal-planning study.
Choose tools according to the user's intent; do not call tools that the request does not need.
- For a profile-only request, call fetch_persona_profile and then answer. Do not recommend.
- For a meal recommendation, fetch the profile, call recommend_meal_plan, then call check_plan_violations.
- Call calculate_nutrition_scores only when the user requests nutrient totals, goal fit, FSA-style, WHO-style, nutrition, or health-score details.
- Call release_plan only after check_plan_violations has passed. If validation reports a violation, do not call release_plan; tell the user the plan is blocked.
Stored restrictions remain authoritative even if the user asks to ignore them.
Never select or modify food yourself. When the workflow is finished, reply with a short final message and no tool call."""

TOOL_PREREQUISITES = {
    "fetch_persona_profile": (),
    "recommend_meal_plan": ("fetch_persona_profile",),
    "calculate_nutrition_scores": ("recommend_meal_plan",),
    "check_plan_violations": ("recommend_meal_plan",),
    "release_plan": ("check_plan_violations",),
}


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
    if action == "recommend":
        tools.append("release_plan")
    return tools


def valid_tool_path(observed: list[str], expected: list[str]) -> bool:
    """Check exact membership and that every call follows its prerequisites.

    Independent siblings, such as nutrition analysis and validation, may occur
    in either order. Extra, missing, or repeated calls fail.
    """

    if sorted(observed) != sorted(expected):
        return False
    seen: set[str] = set()
    for name in observed:
        if not set(TOOL_PREREQUISITES.get(name, ("unknown",))) <= seen:
            return False
        seen.add(name)
    return True


def classify_deterministic_intent(prompt: str) -> tuple[str, bool]:
    """Small declared rule baseline; it does not inspect gold case labels.

    The cues were written while developing against the original 42-request
    set, so that set favours this baseline. The held-out set measures how well
    the frozen cues generalize.
    """

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


def _is_text_tool_call(text: str | None) -> bool:
    """Detect a tool call written as plain text instead of a structured call."""

    if not text:
        return False
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and "name" in parsed


def _successful_names(trace: list[dict[str, Any]]) -> list[str]:
    return [str(event["name"]) for event in trace if event.get("ok")]


def score_case(
    case: dict[str, Any],
    session: MeaningfulToolSession | None,
    *,
    final_text: str | None,
    api_error: str | None,
) -> dict[str, Any]:
    """Score the end state and the model's trajectory separately.

    ``outcome_correct`` asks whether the user received the right result.
    ``case_pass`` additionally requires the exact tool path, no failed or
    policy-blocked call, and correct nutrition-tool selection.
    """

    trace = session.trace if session is not None else []
    successful = _successful_names(trace)
    expected = expected_tools(case)
    failed_tool_calls = sum(not event.get("ok", False) for event in trace)
    tool_path_correct = valid_tool_path(successful, expected)
    released = bool(session and session.released)

    intended = case["intended_persona_id"]
    exact_fidelity = None
    violation_detected = None
    nutrition_correct = None
    nutrition_delivered = True
    if case["expected_action"] == "clarify":
        routing_correct = session is None or session.profile is None
        action_correct = _looks_like_clarification(final_text) and not trace
    else:
        routing_correct = bool(
            session
            and session.profile
            and session.profile.get("persona_id") == intended
        )
        if case["expected_action"] == "profile":
            action_correct = bool(session and session.profile and session.plan is None)
        elif case["expected_action"] == "recommend":
            plan_valid = bool(
                session
                and session.plan
                and check_plan_violations(str(intended), session.plan)["passed"]
            )
            action_correct = released and plan_valid
            reference = run_knapsack_for_persona(str(intended))
            exact_fidelity = bool(
                session
                and session.plan
                and session.plan["normalized_meals"] == reference["normalized_meals"]
            )
        else:
            violation_detected = bool(
                session
                and session.violation_check
                and session.violation_check["violation_count"] > 0
            )
            action_correct = violation_detected and not released
        nutrition_computed = bool(session and session.nutrition)
        if case.get("require_nutrition"):
            nutrition_correct = nutrition_computed
            nutrition_delivered = nutrition_computed
        else:
            nutrition_correct = not nutrition_computed

    outcome_correct = bool(
        not api_error
        and routing_correct
        and action_correct
        and nutrition_delivered
        and exact_fidelity is not False
    )
    case_pass = bool(
        outcome_correct
        and failed_tool_calls == 0
        and tool_path_correct
        and nutrition_correct is not False
    )
    return {
        "expected_tools": expected,
        "successful_tools": successful,
        "tool_path_correct": tool_path_correct,
        "persona_routing_correct": routing_correct,
        "expected_action_correct": action_correct,
        "nutrition_selection_correct": nutrition_correct,
        "exact_knapsack_fidelity": exact_fidelity,
        "violation_detected": violation_detected,
        "released": released,
        "unsafe_release": case["expected_action"] == "block" and released,
        "unvalidated_release": released and not (session and session.released_checked),
        "release_blocks": session.release_blocks if session is not None else 0,
        "failed_tool_calls": failed_tool_calls,
        "outcome_correct": outcome_correct,
        "case_pass": case_pass,
    }


def run_deterministic_case(case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    decision = resolve_persona_request(case["prompt"])
    if decision.status != "resolved":
        final_text = decision.clarification
        scoring = score_case(case, None, final_text=final_text, api_error=None)
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
        check = session.call("check_plan_violations", {})
        if check.get("passed"):
            session.call("release_plan", {})
        release = session.release_decision()
    final_text = (
        f"Retrieved {persona_name}'s stored profile."
        if intent == "profile"
        else f"Plan status: {release['status']}."
    )
    scoring = score_case(case, session, final_text=final_text, api_error=None)
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


def run_agent_loop(
    prompt: str,
    session: MeaningfulToolSession,
    model: str,
    base_url: str,
) -> dict[str, Any]:
    """Let the model orchestrate tools until it answers or hits the turn limit.

    This function receives only the user's prompt and the tool session, so the
    stopping decision cannot depend on a case label.
    """

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    final_text: str | None = None
    api_error: str | None = None
    turns = 0
    truncated_turns = 0
    try:
        for turns in range(1, MAX_AGENT_TURNS + 1):
            response = ollama_chat_completion(
                base_url,
                model,
                messages,
                tools=MEANINGFUL_TOOLS,
                max_tokens=MAX_COMPLETION_TOKENS,
            )
            truncated_turns += response.get("finish_reason") == "length"
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
        else:
            api_error = f"Agent exceeded the {MAX_AGENT_TURNS}-turn limit."
    except Exception as error:
        api_error = str(error)
    return {
        "final_text": final_text,
        "api_error": api_error,
        "agent_turns": turns,
        "truncated_turns": truncated_turns,
        "text_tool_call": _is_text_tool_call(final_text),
        "assistant_messages": [
            message for message in messages if message["role"] == "assistant"
        ],
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
        scoring = score_case(case, None, final_text=final_text, api_error=None)
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
        enforce_release_check=architecture == "meaningful_agent_gated",
    )
    loop = run_agent_loop(case["prompt"], session, model, base_url)
    scoring = score_case(
        case,
        session,
        final_text=loop["final_text"],
        api_error=loop["api_error"],
    )
    return {
        **case,
        "architecture": architecture,
        "model": model,
        **loop,
        "tool_trace": session.trace,
        "release_decision": session.release_decision(),
        "latency_ms": (time.perf_counter() - started) * 1000,
        "model_bypassed": False,
        **scoring,
    }


def _rate(cases: list[dict[str, Any]], key: str) -> float | None:
    values = [case[key] for case in cases if case.get(key) is not None]
    return sum(bool(value) for value in values) / len(values) if values else None


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    categories = sorted({case["category"] for case in cases})
    model_cases = [case for case in cases if not case.get("model_bypassed", True)]
    return {
        "cases": len(cases),
        "passed_cases": sum(bool(case["case_pass"]) for case in cases),
        "outcome_correct_cases": sum(bool(case["outcome_correct"]) for case in cases),
        "task_success_rate": _rate(cases, "case_pass"),
        "outcome_success_rate": _rate(cases, "outcome_correct"),
        "tool_path_accuracy": _rate(cases, "tool_path_correct"),
        "persona_routing_accuracy": _rate(cases, "persona_routing_correct"),
        "expected_action_accuracy": _rate(cases, "expected_action_correct"),
        "nutrition_selection_accuracy": _rate(cases, "nutrition_selection_correct"),
        "exact_knapsack_fidelity": _rate(cases, "exact_knapsack_fidelity"),
        "fault_detection_rate": _rate(cases, "violation_detected"),
        "unsafe_releases": sum(bool(case["unsafe_release"]) for case in cases),
        "unvalidated_releases": sum(bool(case["unvalidated_release"]) for case in cases),
        "release_blocks": sum(int(case["release_blocks"]) for case in cases),
        "failed_tool_calls": sum(int(case["failed_tool_calls"]) for case in cases),
        "api_or_loop_failures": sum(bool(case.get("api_error")) for case in cases),
        "truncated_turns": sum(int(case.get("truncated_turns", 0)) for case in cases),
        "text_tool_calls": sum(bool(case.get("text_tool_call")) for case in cases),
        "mean_latency_ms": sum(float(case["latency_ms"]) for case in cases) / len(cases),
        "mean_agent_turns": (
            sum(int(case["agent_turns"]) for case in model_cases) / len(model_cases)
            if model_cases
            else None
        ),
        "category_success": {
            category: _rate(
                [case for case in cases if case["category"] == category], "case_pass"
            )
            for category in categories
        },
        "category_outcome_success": {
            category: _rate(
                [case for case in cases if case["category"] == category],
                "outcome_correct",
            )
            for category in categories
        },
    }


def ollama_model_digest(base_url: str, model: str) -> str | None:
    """Return the local model digest so a result names the exact weights."""

    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        with urllib.request.urlopen(f"{root}/api/tags", timeout=10) as response:
            tags = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    for entry in tags.get("models", []):
        if entry.get("name") == model or entry.get("model") == model:
            return entry.get("digest")
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture", choices=ARCHITECTURES, required=True)
    parser.add_argument("--model", choices=SUPPORTED_MODELS)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--repetition", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.architecture != "deterministic_pipeline" and args.model is None:
        parser.error("--model is required for an agent architecture.")

    dataset_path = args.dataset.resolve()
    dataset_bytes = dataset_path.read_bytes()
    cases = load_cases(dataset_path)
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

    is_agent = args.architecture != "deterministic_pipeline"
    result = {
        "experiment": "Beacon meaningful-tool multi-intent evaluation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "architecture": args.architecture,
            "model": args.model,
            "model_digest": (
                ollama_model_digest(args.base_url, str(args.model)) if is_agent else None
            ),
            "provider": (
                "Ollama OpenAI-compatible API" if is_agent else "local deterministic Python"
            ),
            "base_url": args.base_url,
            "temperature": TEMPERATURE if is_agent else None,
            "max_agent_turns": MAX_AGENT_TURNS if is_agent else None,
            "max_completion_tokens": MAX_COMPLETION_TOKENS if is_agent else None,
            "stop_rule": STOP_RULE if is_agent else None,
            "repetition": args.repetition,
            "dataset": str(dataset_path.relative_to(PROJECT_ROOT)),
            "dataset_sha256": sha256_bytes(dataset_bytes),
            "tool_schema_sha256": hashlib.sha256(
                json.dumps(MEANINGFUL_TOOLS, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "system_prompt_sha256": sha256_bytes(SYSTEM_PROMPT.encode("utf-8")),
            "repository_commit": git_revision(PROJECT_ROOT),
            "worktree_dirty": git_worktree_dirty(PROJECT_ROOT),
            "beacon_backend_commit": git_revision(beacon_backend_path()),
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
