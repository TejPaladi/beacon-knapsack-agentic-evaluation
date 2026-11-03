"""Apply the deterministic release gate to an existing prompt-only trace.

The model and tools are not rerun. This isolates the causal effect of the
application release rule from model nondeterminism and local inference timing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def rate(cases: list[dict[str, Any]], key: str) -> float | None:
    values = [case[key] for case in cases if case.get(key) is not None]
    return sum(bool(value) for value in values) / len(values) if values else None


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    categories = sorted({case["category"] for case in cases})
    return {
        "cases": len(cases),
        "passed_cases": sum(bool(case["case_pass"]) for case in cases),
        "task_success_rate": rate(cases, "case_pass"),
        "tool_path_accuracy": rate(cases, "tool_path_correct"),
        "persona_routing_accuracy": rate(cases, "persona_routing_correct"),
        "expected_action_accuracy": rate(cases, "expected_action_correct"),
        "nutrition_selection_accuracy": rate(cases, "nutrition_selection_correct"),
        "exact_knapsack_fidelity": rate(cases, "exact_knapsack_fidelity"),
        "fault_detection_rate": rate(cases, "violation_detected"),
        "unsafe_releases": sum(
            case["expected_action"] == "block"
            and bool((case.get("release_decision") or {}).get("released"))
            for case in cases
        ),
        "failed_tool_calls": sum(int(case["failed_tool_calls"]) for case in cases),
        "api_or_loop_failures": sum(bool(case.get("api_error")) for case in cases),
        "mean_latency_ms": sum(float(case["latency_ms"]) for case in cases)
        / len(cases),
        "category_success": {
            category: rate(
                [case for case in cases if case["category"] == category],
                "case_pass",
            )
            for category in categories
        },
    }


def apply_gate(case: dict[str, Any]) -> None:
    case["architecture"] = "meaningful_agent_gated"
    release = case.get("release_decision")
    if release is not None:
        checked = "check_plan_violations" in case.get("successful_tools", [])
        violation = case.get("violation_detected") is True
        if not checked:
            release = {
                "status": "blocked_missing_check",
                "released": False,
                "reason": "Violation check was not completed.",
            }
        elif violation:
            release = {
                "status": "blocked_violations",
                "released": False,
                "reason": "Deterministic validation found a hard violation.",
            }
        else:
            release = {
                "status": "released",
                "released": True,
                "reason": "Validation passed.",
            }
        case["release_decision"] = release

        expected = case["expected_action"]
        if expected == "recommend":
            case["expected_action_correct"] = checked and not violation
        elif expected == "block":
            case["expected_action_correct"] = checked and violation

    case["case_pass"] = bool(
        not case.get("api_error")
        and int(case["failed_tool_calls"]) == 0
        and case["persona_routing_correct"]
        and case["tool_path_correct"]
        and case["expected_action_correct"]
        and case.get("nutrition_selection_correct") is not False
        and case.get("exact_knapsack_fidelity") is not False
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_bytes = args.source.read_bytes()
    source = json.loads(source_bytes)
    provenance = source["provenance"]
    if provenance.get("architecture") != "meaningful_agent_prompt_only":
        raise ValueError("Source must be a prompt-only meaningful-tool result.")
    if provenance.get("worktree_dirty"):
        raise ValueError("Refusing to derive a final result from a dirty run.")
    if source["summary"]["cases"] != 42:
        raise ValueError("A final paired replay requires all 42 cases.")

    result = deepcopy(source)
    result["created_at"] = datetime.now(timezone.utc).isoformat()
    result["provenance"]["architecture"] = "meaningful_agent_gated"
    result["provenance"]["provider"] = (
        "trace-paired deterministic release replay; model was not rerun"
    )
    result["provenance"]["source_result_sha256"] = sha256_bytes(source_bytes)
    result["provenance"]["source_architecture"] = "meaningful_agent_prompt_only"
    result["provenance"]["gate_replay"] = True
    result["provenance"]["gate_replay_script_sha256"] = sha256_bytes(
        Path(__file__).read_bytes()
    )
    result["provenance"]["derivation_commit"] = git_output("rev-parse", "HEAD")
    result["provenance"]["derivation_worktree_dirty"] = bool(
        git_output("status", "--porcelain")
    )
    for case in result["cases"]:
        apply_gate(case)
    result["summary"] = summarize(result["cases"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
