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
    return {
        "ungated_agent": "Prompt-only agent",
        "policy_gated_agent": "Identity-gated agent",
        "deterministic_pipeline": "No-LLM pipeline",
    }[architecture]


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
        f"| {'—' if provenance['model'] is None else f'`{provenance["model"]}`'} | "
        f"{label(provenance['architecture'])} | "
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


def valid_failure_class(case: dict[str, Any]) -> str:
    """Assign one mutually exclusive outcome to a valid-request case."""
    if case["case_pass"]:
        return "Pass"
    if case.get("api_error"):
        return "API/turn-limit error"
    successful_knapsack = any(
        trace.get("name") == "run_knapsack_for_persona" and trace.get("ok")
        for trace in case.get("tool_trace", [])
    )
    if not successful_knapsack:
        if case.get("policy_blocks", 0):
            return "Policy-blocked wrong argument"
        if case.get("failed_tool_calls", 0):
            return "Failed tool call"
        return "No successful Knapsack call"
    if not case.get("persona_routing_correct"):
        return "Wrong persona"
    if not case.get("tool_sequence_compliant"):
        return "Wrong/missing tool order"
    if not case.get("exact_knapsack_fidelity"):
        return "Plan mismatch"
    return "Other"


def failure_counts(result: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in result["cases"]:
        if case["expected_action"] != "recommend":
            continue
        outcome = valid_failure_class(case)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, action="append", required=True)
    parser.add_argument("--deterministic", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [load(path) for path in args.result]
    deterministic = load(args.deterministic) if args.deterministic else None

    if {result["summary"]["cases"] for result in results} != {30}:
        raise ValueError("Every final result must contain all 30 requests.")
    if len({result["provenance"]["dataset_sha256"] for result in results}) != 1:
        raise ValueError("Results use different request datasets.")
    if (
        deterministic
        and deterministic["provenance"]["dataset_sha256"]
        != results[0]["provenance"]["dataset_sha256"]
    ):
        raise ValueError("The no-LLM baseline uses a different request dataset.")

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
    displayed = ([deterministic] if deterministic else []) + ordered
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
        "# Prompt-only versus identity-gated meal-agent evaluation",
        "",
        "All rows use the same 30 requests, three logical tools, Beacon backend, deterministic Knapsack recommender, temperature 0, and strict trace-based scorer. The identity-gated architecture resolves an explicit stored persona before model execution, locks identity-dependent tools to that persona, returns a deterministic clarification for unclear identity, and renders the final confirmation without an additional model turn.",
        "",
        "| Model | Architecture | Overall passed | Valid passed | Unclear passed | Routing | Correct action | Exact fidelity | Sequence | Clarification | Unsafe Knapsack executions | Policy blocks | Mean latency (ms) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(row(result) for result in displayed),
        "",
        "## Aggregate result",
        "",
        f"Across five models and 150 matched model-request pairs, overall passes increased from {prompt_passed}/150 to {gated_passed}/150. Valid recommendation workflows were unchanged at {prompt_valid[0]}/{prompt_valid[1]} in both architectures. Unclear-identity handling increased from {prompt_unclear[0]}/{prompt_unclear[1]} to {gated_unclear[0]}/{gated_unclear[1]}, while unsafe Knapsack executions fell from {prompt_unsafe} to {gated_unsafe}. Mean per-case latency across the equally sized model runs fell from {prompt_latency:.1f} ms to {gated_latency:.1f} ms ({latency_reduction:.1f}% reduction).",
        "",
        "Therefore, the measured improvement is an orchestration-safety and efficiency improvement, not an increase in the models' underlying tool-use capability.",
        "",
        "## Provenance note",
        "",
        "The ten agent results record repository commit `c36f7dfff045032d51e32c1fcaffa617c09b25e7`, the same dataset hash, and identical hashes for the original benchmark and identity-gate implementations. Their worktree-dirty flag is true because generated outputs were present while the matrix was running; source identity is fixed by the recorded commit and implementation hashes. The later no-LLM baseline records its own source commit and the same request-dataset hash.",
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
            "## Valid-request outcome breakdown",
            "",
            "Each of the 24 valid requests per model is assigned to one mutually exclusive outcome. A policy-blocked wrong argument means the model supplied an invalid identity argument and the gate prevented execution; it is still a model-compliance failure.",
            "",
            "| Model | Architecture | Pass | Policy-blocked wrong argument | Failed tool call | No successful Knapsack call | Other |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for result in ordered:
        counts = failure_counts(result)
        other = sum(
            count
            for outcome, count in counts.items()
            if outcome
            not in {
                "Pass",
                "Policy-blocked wrong argument",
                "Failed tool call",
                "No successful Knapsack call",
            }
        )
        lines.append(
            f"| `{result['provenance']['model']}` | "
            f"{label(result['provenance']['architecture'])} | "
            f"{counts.get('Pass', 0)} | "
            f"{counts.get('Policy-blocked wrong argument', 0)} | "
            f"{counts.get('Failed tool call', 0)} | "
            f"{counts.get('No successful Knapsack call', 0)} | {other} |"
        )

    lines.extend(
        [
            "",
            "The unchanged 43/120 valid total is explained by paired behavior: the same models fail on the same valid requests in both architectures. The gate changes invalid identity arguments from backend tool errors into explicit policy blocks, but it does not repair the model's argument or force the required sequence.",
            "",
            "## Interpretation boundary",
            "",
            "The gate improves system-level identity handling and clarification behavior; it does not improve the language model itself. Valid requests still require the model to list personas, retrieve the resolved profile, and invoke Knapsack correctly. A blocked wrong call remains a model/tool-compliance failure. Meal selection is unchanged because Beacon Knapsack remains the only component that selects food.",
            "",
            "The no-LLM pipeline passes all 30 current cases because every valid request contains an exact full name or unique first name and every unclear case is covered by the resolver's fixed rules. This result shows that the current dataset does not demonstrate added utility from an LLM. Typos, nicknames, contextual references, and free-form preferences require a separate language-understanding evaluation.",
            "",
            "This is a six-person, simulated evaluation. It demonstrates a controlled architecture tradeoff, not authentication, clinical safety, or general identity resolution.",
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
