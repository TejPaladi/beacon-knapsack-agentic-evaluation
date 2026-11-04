"""Experiment 6: identification followed by the full release-gated workflow.

For each Experiment 5 conversation, four identification methods choose a
person or a clarification: the exact-name gate, the frozen stronger rules, the
model deciding alone, and propose and confirm with a simulated user who
confirms only the labeled person. Every identified person is then handed to
the Experiment 4 agent with the release gate. An agent run depends only on the
conversation and the person, so it is shared by every method that identifies
the same person in this repetition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from beacon_m6 import beacon_backend_path, check_plan_violations, load_personas, run_knapsack_for_persona
    from benchmark import json_safe
    from hard_wording_benchmark import (
        DEFAULT_DATASET,
        MODELS,
        RULE_RESOLVER_PATH,
        SYSTEM_PROMPT as IDENTITY_PROMPT,
        UNCLEAR,
        call_model,
        load_cases,
        parse_answer,
        resolve_exact,
    )
    from meaningful_tools import MEANINGFUL_TOOLS, MeaningfulToolSession
    from meaningful_tools_benchmark import SYSTEM_PROMPT as AGENT_PROMPT, ollama_model_digest, run_agent_loop
    from report_hard_wording import full_name_persona
    from robustness_benchmark import DEFAULT_BASE_URL, git_revision, git_worktree_dirty, sha256_bytes
    from rule_persona_resolver import resolve as resolve_with_rules
except ModuleNotFoundError:
    from code.beacon_m6 import beacon_backend_path, check_plan_violations, load_personas, run_knapsack_for_persona
    from code.benchmark import json_safe
    from code.hard_wording_benchmark import (
        DEFAULT_DATASET,
        MODELS,
        RULE_RESOLVER_PATH,
        SYSTEM_PROMPT as IDENTITY_PROMPT,
        UNCLEAR,
        call_model,
        load_cases,
        parse_answer,
        resolve_exact,
    )
    from code.meaningful_tools import MEANINGFUL_TOOLS, MeaningfulToolSession
    from code.meaningful_tools_benchmark import SYSTEM_PROMPT as AGENT_PROMPT, ollama_model_digest, run_agent_loop
    from code.report_hard_wording import full_name_persona
    from code.robustness_benchmark import DEFAULT_BASE_URL, git_revision, git_worktree_dirty, sha256_bytes
    from code.rule_persona_resolver import resolve as resolve_with_rules


PROJECT_ROOT = Path(__file__).resolve().parents[1]
METHODS = ("exact_rules", "stronger_rules", "model_decides", "propose_confirm")


def handoff_note(persona_id: str) -> str:
    name = load_personas()[persona_id]["name"]
    return (
        f"The application has identified the person for this request as {name} "
        f"(persona ID {persona_id}). Use only this person."
    )


def identify(
    case: dict[str, Any], model_answer: str | None
) -> dict[str, dict[str, Any]]:
    """Return each method's identified persona (None means clarify)."""

    full_name = full_name_persona(case["messages"])
    proposal = model_answer if model_answer not in (None, UNCLEAR) else None
    if full_name is not None:
        confirmed, asked = full_name, False
    else:
        asked = proposal is not None
        confirmed = proposal if proposal == case["expected_persona_id"] else None
    return {
        "exact_rules": {"persona_id": resolve_exact(case["messages"])},
        "stronger_rules": {"persona_id": resolve_with_rules(case["messages"]).persona_id},
        "model_decides": {"persona_id": proposal},
        "propose_confirm": {
            "persona_id": confirmed,
            "confirmation_asked": asked,
            "proposal": None if full_name is not None else proposal,
        },
    }


def run_workflow(
    case: dict[str, Any], persona_id: str, model: str, base_url: str
) -> dict[str, Any]:
    """Run the release-gated Experiment 4 agent for one identified person."""

    started = time.perf_counter()
    session = MeaningfulToolSession(allowed_persona_id=persona_id, enforce_release_check=True)
    loop = run_agent_loop(
        case["messages"], session, model, base_url, system_note=handoff_note(persona_id)
    )
    plan_ok = False
    if session.released and session.plan is not None:
        reference = run_knapsack_for_persona(persona_id)
        plan_ok = bool(
            check_plan_violations(persona_id, session.plan)["passed"]
            and session.plan["normalized_meals"] == reference["normalized_meals"]
        )
    return {
        "case_id": case["case_id"],
        "persona_id": persona_id,
        **loop,
        "tool_trace": session.trace,
        "release_decision": session.release_decision(),
        "released": bool(session.released),
        "released_plan_valid": plan_ok,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def outcome(case: dict[str, Any], persona_id: str | None, run: dict[str, Any] | None) -> str:
    label = case["expected_persona_id"]
    if persona_id is None or run is None:
        return "missed" if label is not None else "correct_clarification"
    if run["released"]:
        if persona_id != label:
            return "wrong_person_release"
        return "right_plan" if run["released_plan_valid"] else "invalid_release"
    if label is None:
        return "no_plan_released"
    return "identified_not_delivered" if persona_id == label else "wrong_person_not_released"


SUCCESS = {"right_plan", "correct_clarification", "no_plan_released"}


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"cases": len(cases)}
    for method in METHODS:
        outcomes = [c["methods"][method]["outcome"] for c in cases]
        summary[method] = {
            "successes": sum(o in SUCCESS for o in outcomes),
            "right_plans": outcomes.count("right_plan"),
            "wrong_person_releases": outcomes.count("wrong_person_release"),
            "clarify_successes": sum(
                o in SUCCESS for c, o in zip(cases, outcomes) if c["expected_persona_id"] is None
            ),
            "identified_not_delivered": outcomes.count("identified_not_delivered"),
            "missed": outcomes.count("missed"),
            "confirmations_asked": sum(
                bool(c["methods"][method].get("confirmation_asked")) for c in cases
            ),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=MODELS, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--repetition", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cases = load_cases(DEFAULT_DATASET)
    runs: dict[tuple[str, str], dict[str, Any]] = {}
    observed = []
    for index, case in enumerate(cases, start=1):
        answer = parse_answer(call_model(args.base_url, args.model, case["messages"])["content"])
        methods = identify(case, answer)
        for choice in methods.values():
            persona_id = choice["persona_id"]
            if persona_id is not None and (case["case_id"], persona_id) not in runs:
                runs[(case["case_id"], persona_id)] = run_workflow(
                    case, persona_id, args.model, args.base_url
                )
        for choice in methods.values():
            run = runs.get((case["case_id"], choice["persona_id"])) if choice["persona_id"] else None
            choice["outcome"] = outcome(case, choice["persona_id"], run)
            choice["success"] = choice["outcome"] in SUCCESS
        observed.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "expected_persona_id": case["expected_persona_id"],
                "model_answer": answer,
                "methods": methods,
            }
        )
        print(f"[{index}/{len(cases)}] {case['case_id']}: "
              + ", ".join(f"{m}={methods[m]['outcome']}" for m in METHODS), flush=True)

    result = {
        "experiment": "end_to_end_propose_confirm",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "model": args.model,
            "model_digest": ollama_model_digest(args.base_url, args.model),
            "repetition": args.repetition,
            "dataset": str(DEFAULT_DATASET.relative_to(PROJECT_ROOT)),
            "dataset_sha256": sha256_bytes(DEFAULT_DATASET.read_bytes()),
            "identity_prompt_sha256": sha256_bytes(IDENTITY_PROMPT.encode("utf-8")),
            "agent_prompt_sha256": sha256_bytes(AGENT_PROMPT.encode("utf-8")),
            "tool_schema_sha256": hashlib.sha256(
                json.dumps(MEANINGFUL_TOOLS, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "rule_resolver_sha256": sha256_bytes(RULE_RESOLVER_PATH.read_bytes()),
            "simulated_user": "confirms only the labeled person",
            "repository_commit": git_revision(PROJECT_ROOT),
            "worktree_dirty": git_worktree_dirty(PROJECT_ROOT),
            "beacon_backend_commit": git_revision(beacon_backend_path()),
        },
        "summary": summarize(observed),
        "cases": observed,
        "agent_runs": list(runs.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
