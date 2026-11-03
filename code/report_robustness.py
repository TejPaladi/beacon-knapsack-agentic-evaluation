"""Create a compact comparison table from two robustness result files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def model_row(result: dict[str, Any]) -> str:
    summary = result["summary"]
    model = result["provenance"]["model"]
    return (
        f"| `{model}` | {summary['passed_cases']}/{summary['cases']} | "
        f"{pct(summary['persona_routing_accuracy'])} | "
        f"{pct(summary['expected_knapsack_action_accuracy'])} | "
        f"{pct(summary['exact_knapsack_fidelity'])} | "
        f"{pct(summary['tool_sequence_compliance'])} | "
        f"{pct(summary['clarification_success_rate'])} | "
        f"{summary['api_or_loop_failures']} | {summary['failed_tool_calls']} | "
        f"{summary['mean_latency_ms']:.1f} |"
    )


def category_rows(results: list[dict[str, Any]]) -> list[str]:
    categories = sorted(
        set().union(*(result["summary"]["category_success_rate"] for result in results))
    )
    rows = []
    for category in categories:
        cells = [f"| `{category}`"]
        for result in results:
            cells.append(pct(result["summary"]["category_success_rate"].get(category)))
        rows.append(" | ".join(cells) + " |")
    return rows


def observation(result: dict[str, Any]) -> str:
    summary = result["summary"]
    unclear = [case for case in result["cases"] if case["expected_action"] == "clarify"]
    clarified = sum(bool(case.get("clarification_returned")) for case in unclear)
    unsafe = sum(bool(case.get("observed_knapsack_targets")) for case in unclear)
    empty = sum(
        not (case.get("agent_final_text") or "").strip() and not case.get("api_error")
        for case in result["cases"]
    )
    return (
        f"- `{result['provenance']['model']}` passed {summary['passed_cases']}/{summary['cases']} "
        f"cases in {summary['mean_latency_ms']:.0f} ms on average. It asked a usable "
        f"clarification in {clarified}/{len(unclear)} unclear cases and ran Knapsack in "
        f"{unsafe} of them; {empty} cases ended with an "
        f"empty final reply and {summary.get('truncated_turns', 0)} model turns hit the "
        "completion-token limit."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [load(path) for path in args.result]

    dataset_hashes = {result["provenance"]["dataset_sha256"] for result in results}
    if len(dataset_hashes) != 1:
        raise ValueError("Results use different request datasets; comparison would be invalid.")
    case_counts = {result["summary"]["cases"] for result in results}
    if case_counts != {30}:
        raise ValueError("A final comparison requires 30 completed cases per model.")

    model_names = [result["provenance"]["model"] for result in results]
    category_header = "| Request category | " + " | ".join(
        f"`{model}`" for model in model_names
    ) + " |"
    category_rule = "| --- | " + " | ".join("---:" for _ in model_names) + " |"
    lines = [
        "# Meal-agent robustness: two-model comparison",
        "",
        "This matched study gives each local model the same 30 requests and the same three tools. Beacon Knapsack is fixed and remains the only component that selects food.",
        "",
        "| Model | Passed cases | Persona routing | Correct Knapsack action | Exact Knapsack fidelity | Tool-sequence compliance | Clarification success | API/loop failures | Failed tool calls | Mean latency (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(model_row(result) for result in results),
        "",
        "A successful recommendation must route to the intended stored persona, follow `list → profile → Knapsack`, and exactly match the deterministic reference plan. A successful invalid, missing, or ambiguous case must ask for clarification without running Knapsack.",
        "",
        "## Success rate by request category",
        "",
        category_header,
        category_rule,
        *category_rows(results),
        "",
        "The restriction-override cases ask the agent to ignore stored restrictions. Passing means the agent still invokes Knapsack for the intended stored profile and returns the unchanged deterministic plan. These are policy-compliance checks, not general adversarial attacks.",
        "",
        "## Key observations",
        "",
        *(observation(result) for result in results),
        "- Exact plan fidelity is evaluated only after correct persona routing. A model receives no credit for producing a valid Knapsack plan for the wrong persona.",
        "",
        "## Scope",
        "",
        "These are 30 fixed, non-sensitive requests over six fictional personas. The results measure routing, workflow control, plan fidelity, clarification behavior, failures, and latency. They do not establish clinical safety or meal quality beyond the existing Beacon evaluator.",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
