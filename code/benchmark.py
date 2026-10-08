"""Run the direct Beacon Knapsack or agentic-Knapsack evaluation condition.

The agent has no food-selection tool.  It can identify a persona, retrieve the
profile, and invoke the same deterministic Knapsack pipeline used by the direct
Beacon+ condition.  This isolates orchestration from recommendation quality.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # Works both as ``python code/benchmark.py`` and as a package module.
    from beacon_m6 import (
        beacon_backend_path,
        evaluate_knapsack_plan,
        list_personas,
        load_personas,
        public_persona,
        run_knapsack_for_persona,
    )
except ModuleNotFoundError:
    from code.beacon_m6 import (
        beacon_backend_path,
        evaluate_knapsack_plan,
        list_personas,
        load_personas,
        public_persona,
        run_knapsack_for_persona,
    )


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = EXPERIMENT_ROOT / "results"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Groq's Cloudflare edge rejects Python's default ``Python-urllib/x.y`` client
# signature with HTTP 403 / error code 1010 before the request reaches Groq.
# Use an explicit, browser-compatible signature for this standard HTTPS request.
GROQ_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36 Beacon-Knapsack-Evaluation/1.0"
)
MAX_RATE_LIMIT_RETRIES = 8
RATE_LIMIT_BUFFER_SECONDS = 0.5
MAX_TOOL_FORMAT_RETRIES = 2
_RETRY_SECONDS = re.compile(r"try again in\s+([0-9.]+)s", re.IGNORECASE)

SYSTEM_PROMPT = """You are the orchestration layer for Beacon meal planning.
For every request, follow this workflow in order:
1. Call list_personas to map the requested name to an identifier.
2. Call get_persona for that identifier.
3. Call run_knapsack_for_persona for that same identifier.
Do not choose food, modify the returned plan, or claim numerical nutrition-goal optimization.
After the Knapsack tool returns, give a short confirmation that the plan is ready."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_personas",
            "description": "List available Beacon personas with identifiers and names.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_persona",
            "description": "Retrieve the stored preferences, dietary conditions, meal roles, and goals for one Beacon persona.",
            "parameters": {
                "type": "object",
                "properties": {"persona_id": {"type": "string"}},
                "required": ["persona_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_knapsack_for_persona",
            "description": "Run Beacon's deterministic Knapsack pipeline for a retrieved persona and return its one-day plan.",
            "parameters": {
                "type": "object",
                "properties": {"persona_id": {"type": "string"}},
                "required": ["persona_id"],
                "additionalProperties": False,
            },
        },
    },
]


def json_safe(value: Any) -> Any:
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


def role_complete(plan: dict[str, Any], persona_id: str) -> bool:
    expected = public_persona(persona_id)["meal_roles"]
    actual = plan.get("meals", [])
    if len(actual) != len(expected):
        return False
    for expected_meal, actual_meal in zip(expected, actual):
        if expected_meal["meal_name"] != actual_meal.get("meal_name"):
            return False
        returned_roles = {item["role"] for item in actual_meal.get("items", [])}
        requested_roles = {
            {"mainCourse": "main_course", "side": "side", "dessert": "dessert", "beverage": "beverage"}[role]
            for role in expected_meal["roles"]
        }
        if returned_roles != requested_roles:
            return False
    return True


def direct_case(persona_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    plan = run_knapsack_for_persona(persona_id)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "persona_id": persona_id,
        "persona_name": plan["persona_name"],
        "prompt": None,
        "plan": plan,
        "valid_role_coverage": role_complete(plan, persona_id),
        "matches_direct_knapsack": True,
        "quality_evaluation": evaluate_knapsack_plan(persona_id, plan),
        "tool_sequence_valid": None,
        "api_error": None,
        "latency_ms": elapsed_ms,
    }


class ToolSession:
    """Stateful, restricted access to the three agent tools for one request."""

    def __init__(self) -> None:
        self.trace: list[dict[str, Any]] = []
        self.retrieved_personas: set[str] = set()
        self.knapsack_plan: dict[str, Any] | None = None

    @staticmethod
    def _compact_plan_for_model(plan: dict[str, Any]) -> dict[str, Any]:
        """Return only what the model needs after Knapsack has selected the plan.

        The full plan remains in ``knapsack_plan`` for evaluation. Omitting internal
        fields (normalization data, catalog scope, and evaluation metadata)
        keeps tool-result tokens low and reduces avoidable provider rate limits.
        """

        return {
            "persona_id": plan["persona_id"],
            "persona_name": plan["persona_name"],
            "algorithm": plan["algorithm"],
            "meals": plan["meals"],
        }

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "list_personas":
                result: Any = list_personas()
            elif name == "get_persona":
                persona_id = str(arguments["persona_id"])
                result = public_persona(persona_id)
                self.retrieved_personas.add(persona_id)
            elif name == "run_knapsack_for_persona":
                persona_id = str(arguments["persona_id"])
                if persona_id not in self.retrieved_personas:
                    raise ValueError("Retrieve this persona with get_persona before calling Knapsack.")
                result = run_knapsack_for_persona(persona_id)
                self.knapsack_plan = result
                result = self._compact_plan_for_model(result)
            else:
                raise ValueError(f"Unknown tool: {name}")
            event = {"name": name, "arguments": arguments, "ok": True}
            self.trace.append(event)
            return result
        except Exception as error:  # Tool errors are part of the measured trace.
            event = {"name": name, "arguments": arguments, "ok": False, "error": str(error)}
            self.trace.append(event)
            return {"error": str(error)}


class GroqRateLimitError(RuntimeError):
    """A retryable Groq 429 response with its requested wait time."""

    def __init__(self, message: str, retry_after_seconds: float):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class GroqToolFormatError(RuntimeError):
    """Groq rejected a model-produced tool call before returning a message.

    This is distinct from a tool error: the local tool was never called.  A
    fresh model request with a short JSON-format reminder is safe, because no
    side effect or recommendation has occurred yet.
    """


def chat_completion(api_key: str, model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "temperature": 0,
            "max_completion_tokens": 96,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        GROQ_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": GROQ_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if error.code == 429:
            match = _RETRY_SECONDS.search(detail)
            retry_after = float(match.group(1)) if match else 5.0
            raise GroqRateLimitError(
                f"Groq HTTP 429 rate limit; retry after {retry_after:.1f}s.",
                retry_after,
            ) from error
        if error.code == 400 and "tool_use_failed" in detail:
            raise GroqToolFormatError(
                "Groq rejected a malformed model tool-call argument payload."
            ) from error
        raise RuntimeError(f"Groq HTTP {error.code}: {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Groq connection error: {error.reason}") from error
    return body["choices"][0]["message"]


def chat_completion_with_retry(
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    max_retries: int = MAX_RATE_LIMIT_RETRIES,
) -> tuple[dict[str, Any], int, float, int]:
    """Handle transient rate limits and provider-rejected tool JSON safely.

    A 429 retry waits for Groq's requested interval.  A ``tool_use_failed``
    response occurs before the provider executes any local tool; we retry the
    request with an explicit strict-JSON reminder.  Both retry types are
    retained in the result telemetry instead of being counted as Knapsack failures.
    """

    total_wait_seconds = 0.0
    rate_limit_retries = 0
    tool_format_retries = 0
    while True:
        try:
            return (
                chat_completion(api_key, model, messages),
                rate_limit_retries,
                total_wait_seconds,
                tool_format_retries,
            )
        except GroqRateLimitError as error:
            if rate_limit_retries >= max_retries:
                raise
            wait_seconds = max(1.0, error.retry_after_seconds + RATE_LIMIT_BUFFER_SECONDS)
            print(
                f"Groq rate limit; waiting {wait_seconds:.1f}s before retry "
                f"({rate_limit_retries + 1}/{max_retries}).",
                flush=True,
            )
            time.sleep(wait_seconds)
            total_wait_seconds += wait_seconds
            rate_limit_retries += 1
        except GroqToolFormatError:
            if tool_format_retries >= MAX_TOOL_FORMAT_RETRIES:
                raise
            tool_format_retries += 1
            print(
                "Groq rejected malformed tool-call JSON; retrying with a format reminder "
                f"({tool_format_retries}/{MAX_TOOL_FORMAT_RETRIES}).",
                flush=True,
            )
            # The provider did not return an assistant message, so do not
            # fabricate one.  Place the correction before the original user
            # request and reissue the request with the real conversation only.
            messages.insert(
                1,
                {
                    "role": "system",
                    "content": (
                        "Retry the next tool call using strict JSON arguments only: "
                        "double-quoted keys and values, no comments, no trailing text. "
                        "Call one tool at a time."
                    ),
                },
            )


def clean_assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    clean = {"role": "assistant", "content": message.get("content")}
    calls = []
    for call in message.get("tool_calls") or []:
        calls.append(
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["function"]["name"],
                    "arguments": call["function"]["arguments"],
                },
            }
        )
    if calls:
        clean["tool_calls"] = calls
    return clean


def valid_tool_sequence(trace: list[dict[str, Any]], persona_id: str) -> bool:
    successful = [event for event in trace if event["ok"]]
    names = [event["name"] for event in successful]
    try:
        listed = names.index("list_personas")
        profile = next(
            index
            for index, event in enumerate(successful)
            if event["name"] == "get_persona" and event["arguments"].get("persona_id") == persona_id
        )
        knapsack = next(
            index
            for index, event in enumerate(successful)
            if event["name"] == "run_knapsack_for_persona" and event["arguments"].get("persona_id") == persona_id
        )
    except (StopIteration, ValueError):
        return False
    return listed < profile < knapsack


def agentic_case(persona_id: str, api_key: str, model: str) -> dict[str, Any]:
    persona = public_persona(persona_id)
    prompt = f"Create a one-day meal plan for {persona['name']}."
    reference = run_knapsack_for_persona(persona_id)
    session = ToolSession()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    started = time.perf_counter()
    final_text = None
    api_error = None
    rate_limit_retries = 0
    rate_limit_wait_seconds = 0.0
    tool_format_retries = 0
    try:
        for _ in range(6):
            response, retries, waited, format_retries = chat_completion_with_retry(
                api_key, model, messages
            )
            rate_limit_retries += retries
            rate_limit_wait_seconds += waited
            tool_format_retries += format_retries
            messages.append(clean_assistant_message(response))
            calls = response.get("tool_calls") or []
            if not calls:
                final_text = response.get("content")
                break
            for call in calls:
                try:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                result = session.call(call["function"]["name"], arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(json_safe(result)),
                    }
                )
        else:
            api_error = "Agent exceeded the six-turn tool-loop limit."
    except Exception as error:  # API errors are recorded, never scored as incorrect output.
        api_error = str(error)
    elapsed_ms = (time.perf_counter() - started) * 1000
    observed = session.knapsack_plan
    return {
        "persona_id": persona_id,
        "persona_name": persona["name"],
        "prompt": prompt,
        "plan": observed,
        "reference_plan": reference,
        "valid_role_coverage": bool(observed and role_complete(observed, persona_id)),
        "matches_direct_knapsack": bool(
            observed and observed["normalized_meals"] == reference["normalized_meals"]
        ),
        "quality_evaluation": (
            evaluate_knapsack_plan(persona_id, observed) if observed is not None else None
        ),
        "tool_sequence_valid": valid_tool_sequence(session.trace, persona_id),
        "tool_trace": session.trace,
        "agent_final_text": final_text,
        "api_error": api_error,
        "latency_ms": elapsed_ms,
        "rate_limit_retries": rate_limit_retries,
        "rate_limit_wait_seconds": rate_limit_wait_seconds,
        "tool_format_retries": tool_format_retries,
        "latency_excluding_rate_limit_wait_ms": max(
            0.0, elapsed_ms - rate_limit_wait_seconds * 1000
        ),
    }


def _mean_quality_metric(
    cases: list[dict[str, Any]], section: str, field: str
) -> float | None:
    """Average one Beacon evaluation value across completed, scored cases."""

    values = []
    for case in cases:
        evaluation = case.get("quality_evaluation") or {}
        value = (evaluation.get(section) or {}).get(field)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return sum(values) / len(values) if values else None


def summarize(condition: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [case for case in cases if not case["api_error"]]
    return {
        "condition": condition,
        "cases": len(cases),
        "completed_cases": len(completed),
        "api_or_timeout_failures": len(cases) - len(completed),
        "role_coverage_rate": (
            sum(case["valid_role_coverage"] for case in completed) / len(completed)
            if completed
            else None
        ),
        "knapsack_fidelity_rate": (
            sum(case["matches_direct_knapsack"] for case in completed) / len(completed)
            if completed
            else None
        ),
        "tool_sequence_rate": (
            sum(case["tool_sequence_valid"] is True for case in completed) / len(completed)
            if completed and condition == "agentic_knapsack"
            else None
        ),
        "mean_legacy_goodness": _mean_quality_metric(
            completed, "legacy_goodness", "score"
        ),
        "mean_beacon_quality_score": _mean_quality_metric(
            completed, "quality", "quality_score"
        ),
        "mean_nutrition_goal_fit": _mean_quality_metric(
            completed, "nutrition_goal_adherence", "mean_fit"
        ),
        "mean_latency_ms": (
            sum(case["latency_ms"] for case in completed) / len(completed) if completed else None
        ),
        "total_rate_limit_retries": sum(
            case.get("rate_limit_retries", 0) for case in completed
        ),
        "total_rate_limit_wait_seconds": sum(
            case.get("rate_limit_wait_seconds", 0.0) for case in completed
        ),
        "total_tool_format_retries": sum(
            case.get("tool_format_retries", 0) for case in completed
        ),
        "mean_latency_excluding_rate_limit_wait_ms": (
            sum(case.get("latency_excluding_rate_limit_wait_ms", case["latency_ms"]) for case in completed)
            / len(completed)
            if completed
            else None
        ),
        "status": "complete" if len(completed) == len(cases) else "incomplete",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--condition", choices=["direct_knapsack", "agentic_knapsack"], required=True
    )
    parser.add_argument("--model", default=os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"))
    parser.add_argument("--limit", type=int, default=None, help="Use only the first N personas for a smoke test.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    personas = list(load_personas())
    if args.limit is not None:
        personas = personas[: args.limit]
    if not personas:
        raise ValueError("No personas selected.")

    api_key = None
    if args.condition == "agentic_knapsack":
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is required for the agentic_knapsack condition.")

    cases = []
    for index, persona_id in enumerate(personas, start=1):
        print(f"[{index}/{len(personas)}] {args.condition}: {persona_id}", flush=True)
        if args.condition == "direct_knapsack":
            cases.append(direct_case(persona_id))
        else:
            cases.append(agentic_case(persona_id, api_key, args.model))

    result = {
        "experiment": "Beacon Knapsack direct versus agentic orchestration",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "condition": args.condition,
        "model": args.model if args.condition == "agentic_knapsack" else None,
        "beacon_backend": str(beacon_backend_path()),
        "summary": summarize(args.condition, cases),
        "cases": cases,
    }
    RESULTS_DIR.mkdir(exist_ok=True)
    output = args.output or RESULTS_DIR / (
        f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{args.condition}.json"
    )
    output.write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
