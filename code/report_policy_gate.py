"""Create the matched prompt-only versus policy-gated robustness report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def label(architecture: str) -> str:
    return "Prompt-only" if architecture == "ungated_agent" else "Policy-gated"


def row(result: dict[str, Any]) -> str:
    summary = result["summary"]
    provenance = result["provenance"]
    return (
        f"| `{provenance['model']}` | {label(provenance['architecture'])} | "
        f"{summary['passed_cases']}/{summary['cases']} | "
        f"{pct(summary['persona_routing_accuracy'])} | "
        f"{pct(summary['expected_knapsack_action_accuracy'])} | "
        f"{pct(summary['exact_knapsack_fidelity'])} | "
        f"{pct(summary['tool_sequence_compliance'])} | "
        f"{pct(summary['clarification_success_rate'])} | "
        f"{summary.get('unsafe_knapsack_executions', 0)} | "
        f"{summary.get('policy_blocks', 0)} | "
        f"{summary['mean_latency_ms']:.1f} |"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [load(path) for path in args.result]

    if {result["summary"]["cases"] for result in results} != {30}:
        raise ValueError("Every final result must contain all 30 requests.")
    if len({result["provenance"]["dataset_sha256"] for result in results}) != 1:
        raise ValueError("Results use different request datasets.")

    by_pair = {
        (result["provenance"]["model"], result["provenance"]["architecture"]): result
        for result in results
    }
    models = sorted({model for model, _ in by_pair})
    for model in models:
        missing = {
            "ungated_agent",
            "policy_gated_agent",
        } - {architecture for candidate, architecture in by_pair if candidate == model}
        if missing:
            raise ValueError(f"Missing matched architecture for {model}: {sorted(missing)}")

    ordered = [
        by_pair[(model, architecture)]
        for model in models
        for architecture in ("ungated_agent", "policy_gated_agent")
    ]
    lines = [
        "# Prompt-only versus policy-gated meal-agent evaluation",
        "",
        "All rows use the same 30 requests, three logical tools, Beacon backend, deterministic Knapsack recommender, temperature 0, and strict trace-based scorer. The policy-gated architecture resolves an explicit stored persona before model execution, locks identity-dependent tools to that persona, returns a deterministic clarification for unclear identity, and renders the final confirmation without an additional model turn.",
        "",
        "| Model | Architecture | Passed | Routing | Correct action | Exact fidelity | Sequence | Clarification | Unsafe Knapsack executions | Policy blocks | Mean latency (ms) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(row(result) for result in ordered),
        "",
        "## Matched improvement",
        "",
    ]
    for model in models:
        ungated = by_pair[(model, "ungated_agent")]["summary"]
        gated = by_pair[(model, "policy_gated_agent")]["summary"]
        delta = gated["passed_cases"] - ungated["passed_cases"]
        lines.append(
            f"- `{model}`: {ungated['passed_cases']}/30 → {gated['passed_cases']}/30 "
            f"({delta:+d}); clarification {pct(ungated['clarification_success_rate'])} → "
            f"{pct(gated['clarification_success_rate'])}; unsafe unclear-case Knapsack "
            f"executions {ungated.get('unsafe_knapsack_executions', 0)} → "
            f"{gated.get('unsafe_knapsack_executions', 0)}."
        )

    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "The gate improves system-level identity safety and clarification behavior; it does not improve the language model itself. Valid requests still require the model to list personas, retrieve the authorized profile, and invoke Knapsack correctly. A blocked wrong call remains a model/tool-compliance failure. Meal selection is unchanged because Beacon Knapsack remains the only component that selects food.",
            "",
            "This is a six-person, simulated evaluation. It demonstrates a controlled architecture tradeoff, not clinical safety or general identity resolution.",
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
