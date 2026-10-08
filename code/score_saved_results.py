"""Attach Beacon quality metrics to a completed saved experiment run.

This script does not generate recommendations and does not contact an LLM. It
only evaluates the meal IDs already returned in a saved direct or agentic run
with Beacon's existing Knapsack-quality code.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    from beacon_m6 import evaluate_knapsack_plan
    from benchmark import summarize
except ModuleNotFoundError:
    from code.beacon_m6 import evaluate_knapsack_plan
    from code.benchmark import summarize


def _rename_plan(plan: dict[str, Any] | None) -> None:
    if plan is not None:
        plan["algorithm"] = "Beacon Knapsack"


def score_case(case: dict[str, Any]) -> dict[str, Any]:
    updated = deepcopy(case)
    observed_plan = updated.get("plan")
    _rename_plan(observed_plan)
    _rename_plan(updated.get("reference_plan"))

    # Earlier saved outputs used Beacon's internal M6 name. Translate the
    # experiment schema to the public Knapsack terminology without changing a
    # recommendation, a trace order, or an evaluation outcome.
    if "matches_direct_knapsack" not in updated:
        updated["matches_direct_knapsack"] = bool(
            updated.pop("matches_direct_m6", False)
        )
    if "tool_trace" in updated:
        for event in updated["tool_trace"]:
            if event.get("name") == "run_m6_for_persona":
                event["name"] = "run_knapsack_for_persona"

    if observed_plan is not None:
        updated["quality_evaluation"] = evaluate_knapsack_plan(
            str(updated["persona_id"]), observed_plan
        )
    else:
        updated["quality_evaluation"] = None
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--condition", choices=["direct_knapsack", "agentic_knapsack"], required=True
    )
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    cases = [score_case(case) for case in source.get("cases", [])]
    result = {
        **source,
        "experiment": "Beacon Knapsack direct versus agentic orchestration",
        "condition": args.condition,
        "model": source.get("model") if args.condition == "agentic_knapsack" else None,
        "summary": summarize(args.condition, cases),
        "cases": cases,
        "evaluation_note": (
            "Quality metrics were computed after recommendation generation from the "
            "saved observed meal IDs using Beacon's existing evaluators."
        ),
    }
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
