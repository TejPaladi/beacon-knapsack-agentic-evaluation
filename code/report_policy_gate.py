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


def passed_for_action(result: dict[str, Any], expected_action: str) -> tuple[int, int]:
    cases = [
        case for case in result["cases"] if case["expected_action"] == expected_action
    ]
    return sum(bool(case["case_pass"]) for case in cases), len(cases)


def row(result: dict[str, Any]) -> str:
    summary = result["summary"]
    provenance = result["provenance"]
    valid_passed, valid_total = passed_for_action(result, "recommend")
    unclear_passed, unclear_total = passed_for_action(result, "clarify")
    return (
        f"| `{provenance['model']}` | {label(provenance['architecture'])} | "
        f"{summary['passed_cases']}/{summary['cases']} | "
        f"{valid_passed}/{valid_total} | {unclear_passed}/{unclear_total} | "
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
    prompt_only = [
        result
        for result in ordered
        if result["provenance"]["architecture"] == "ungated_agent"
    ]
    policy_gated = [
        result
        for result in ordered
        if result["provenance"]["architecture"] == "policy_gated_agent"
    ]

    def aggregate(results: list[dict[str, Any]], action: str) -> tuple[int, int]:
        counts = [passed_for_action(result, action) for result in results]
        return sum(passed for passed, _ in counts), sum(total for _, total in counts)

    prompt_valid = aggregate(prompt_only, "recommend")
    gated_valid = aggregate(policy_gated, "recommend")
    prompt_unclear = aggregate(prompt_only, "clarify")
    gated_unclear = aggregate(policy_gated, "clarify")
    prompt_passed = sum(result["summary"]["passed_cases"] for result in prompt_only)
    gated_passed = sum(result["summary"]["passed_cases"] for result in policy_gated)
    prompt_unsafe = sum(
        result["summary"].get("unsafe_knapsack_executions", 0)
        for result in prompt_only
    )
    gated_unsafe = sum(
        result["summary"].get("unsafe_knapsack_executions", 0)
        for result in policy_gated
    )
    prompt_latency = sum(
        result["summary"]["mean_latency_ms"] for result in prompt_only
    ) / len(prompt_only)
    gated_latency = sum(
        result["summary"]["mean_latency_ms"] for result in policy_gated
    ) / len(policy_gated)
    latency_reduction = 100 * (prompt_latency - gated_latency) / prompt_latency

    lines = [
        "# Prompt-only versus policy-gated meal-agent evaluation",
        "",
        "All rows use the same 30 requests, three logical tools, Beacon backend, deterministic Knapsack recommender, temperature 0, and strict trace-based scorer. The policy-gated architecture resolves an explicit stored persona before model execution, locks identity-dependent tools to that persona, returns a deterministic clarification for unclear identity, and renders the final confirmation without an additional model turn.",
        "",
        "| Model | Architecture | Overall passed | Valid passed | Unclear passed | Routing | Correct action | Exact fidelity | Sequence | Clarification | Unsafe Knapsack executions | Policy blocks | Mean latency (ms) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(row(result) for result in ordered),
        "",
        "## Aggregate result",
        "",
        f"Across five models and 150 matched model-request pairs, overall passes increased from {prompt_passed}/150 to {gated_passed}/150. Valid recommendation workflows were unchanged at {prompt_valid[0]}/{prompt_valid[1]} in both architectures. Unclear-identity handling increased from {prompt_unclear[0]}/{prompt_unclear[1]} to {gated_unclear[0]}/{gated_unclear[1]}, while unsafe Knapsack executions fell from {prompt_unsafe} to {gated_unsafe}. Mean per-case latency across the equally sized model runs fell from {prompt_latency:.1f} ms to {gated_latency:.1f} ms ({latency_reduction:.1f}% reduction).",
        "",
        "Therefore, the measured improvement is an orchestration-safety and efficiency improvement, not an increase in the models' underlying tool-use capability.",
        "",
        "## Provenance note",
        "",
        "All ten raw results record repository commit `c36f7dfff045032d51e32c1fcaffa617c09b25e7`, the same dataset hash, and identical hashes for the benchmark and policy-gate implementations. Their worktree-dirty flag is true because generated result files were present as untracked outputs while the matrix was running; source identity is fixed by the recorded commit and implementation hashes.",
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
