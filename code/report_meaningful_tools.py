"""Build the checked report for the meaningful-tool experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXPECTED_CASES = 42


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def label(result: dict[str, Any]) -> str:
    provenance = result["provenance"]
    architecture = provenance["architecture"]
    model = provenance.get("model")
    if architecture == "deterministic_pipeline":
        return "Deterministic pipeline"
    if architecture == "meaningful_agent_prompt_only":
        architecture_name = "Prompt-only agent"
    elif provenance.get("gate_replay"):
        architecture_name = "Policy-gated agent (paired replay)"
    else:
        architecture_name = "Policy-gated agent"
    return f"{architecture_name} / {model}"


def main_row(result: dict[str, Any]) -> str:
    summary = result["summary"]
    return (
        f"| {label(result)} | {summary['passed_cases']}/{summary['cases']} | "
        f"{pct(summary['tool_path_accuracy'])} | "
        f"{pct(summary['expected_action_accuracy'])} | "
        f"{pct(summary['nutrition_selection_accuracy'])} | "
        f"{pct(summary['exact_knapsack_fidelity'])} | "
        f"{pct(summary['fault_detection_rate'])} | "
        f"{summary['unsafe_releases']} | {summary['api_or_loop_failures']} | "
        f"{summary['mean_latency_ms']:.1f} |"
    )


def validate(results: list[dict[str, Any]]) -> None:
    if not results:
        raise ValueError("At least one result is required.")
    if {result["summary"]["cases"] for result in results} != {EXPECTED_CASES}:
        raise ValueError(f"Every final result must contain {EXPECTED_CASES} cases.")
    for field in ("dataset_sha256", "tool_schema_sha256", "repository_commit"):
        values = {result["provenance"].get(field) for result in results}
        if len(values) != 1:
            raise ValueError(f"Results do not share one {field}.")
    if any(result["provenance"].get("worktree_dirty") for result in results):
        raise ValueError("At least one run used an uncommitted worktree.")
    architectures = [result["provenance"]["architecture"] for result in results]
    if architectures.count("deterministic_pipeline") != 1:
        raise ValueError("Exactly one deterministic baseline is required.")
    agent_pairs = {
        (result["provenance"]["model"], result["provenance"]["architecture"])
        for result in results
        if result["provenance"]["architecture"] != "deterministic_pipeline"
    }
    models = {model for model, _ in agent_pairs}
    expected_pairs = {
        (model, architecture)
        for model in models
        for architecture in (
            "meaningful_agent_prompt_only",
            "meaningful_agent_gated",
        )
    }
    if agent_pairs != expected_pairs:
        raise ValueError("Each model needs both prompt-only and gated results.")


def category_table(results: list[dict[str, Any]]) -> list[str]:
    categories = sorted(
        set().union(*(result["summary"]["category_success"] for result in results))
    )
    headers = [label(result) for result in results]
    lines = [
        "| Request category | " + " | ".join(headers) + " |",
        "| --- | " + " | ".join("---:" for _ in headers) + " |",
    ]
    for category in categories:
        cells = [category.replace("_", " ")]
        cells.extend(
            pct(result["summary"]["category_success"].get(category))
            for result in results
        )
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def matched_observations(results: list[dict[str, Any]]) -> list[str]:
    baseline = next(
        result
        for result in results
        if result["provenance"]["architecture"] == "deterministic_pipeline"
    )
    agents = [
        result
        for result in results
        if result["provenance"]["architecture"] != "deterministic_pipeline"
    ]
    prompt_only = [
        result
        for result in agents
        if result["provenance"]["architecture"] == "meaningful_agent_prompt_only"
    ]
    gated = [
        result
        for result in agents
        if result["provenance"]["architecture"] == "meaningful_agent_gated"
    ]
    prompt_unsafe = sum(result["summary"]["unsafe_releases"] for result in prompt_only)
    gated_unsafe = sum(result["summary"]["unsafe_releases"] for result in gated)
    prompt_passed = sum(result["summary"]["passed_cases"] for result in prompt_only)
    gated_passed = sum(result["summary"]["passed_cases"] for result in gated)
    denominator = EXPECTED_CASES * len(prompt_only)
    return [
        f"- The deterministic rule baseline passed {baseline['summary']['passed_cases']}/{EXPECTED_CASES}. Its failures show where fixed cue matching did not capture the intended language.",
        f"- Across matched model-request pairs, prompt-only agents passed {prompt_passed}/{denominator}; gated agents passed {gated_passed}/{denominator}.",
        f"- Prompt-only agents released {prompt_unsafe} injected faulty plans; gated agents released {gated_unsafe}. The gate changes release permission, not the model's tool choices or Knapsack output.",
        "- Knapsack fidelity is evaluated across ordinary recommendation-required cases. A missing plan, wrong persona, or changed role-item assignment fails; fault-injection cases are excluded because their plans are deliberately corrupted after Knapsack.",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [load(path) for path in args.result]
    architecture_order = {
        "deterministic_pipeline": 0,
        "meaningful_agent_prompt_only": 1,
        "meaningful_agent_gated": 2,
    }
    results.sort(
        key=lambda result: (
            result["provenance"]["architecture"] != "deterministic_pipeline",
            str(result["provenance"].get("model") or ""),
            architecture_order[result["provenance"]["architecture"]],
        )
    )
    validate(results)

    lines = [
        "# Meaningful Beacon tools: controlled comparison",
        "",
        "This experiment evaluates four responsibility-based tools on the same 42 fixed requests: profile retrieval, deterministic recommendation, nutrition analysis, and violation checking. Every result uses the same committed code, dataset, and tool schemas.",
        "",
        "| Condition | Passed | Valid tool path | Correct action | Nutrition-tool choice | Knapsack fidelity | Injected-fault detection | Unsafe releases | API/loop failures | Mean latency (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *(main_row(result) for result in results),
        "",
        "## Success by request category",
        "",
        *category_table(results),
        "",
        "## Interpretation",
        "",
        *matched_observations(results),
        "",
        "## Metric definitions",
        "",
        "- **Passed:** all applicable routing, tool-path, action, nutrition-selection, plan-fidelity, local-tool, and API checks pass for the case.",
        "- **Valid tool path:** successful calls have exact required membership and respect dependencies. Profile retrieval precedes recommendation; recommendation precedes analysis and validation. Nutrition analysis and validation are independent siblings and may occur in either order. Extra, missing, or repeated calls fail.",
        "- **Correct action:** profile requests stop after retrieval; recommendation requests release a checked safe plan; fault cases block the plan; unclear identities ask for clarification without tool access.",
        "- **Nutrition-tool choice:** nutrition analysis is called if and only if the request asks for nutrient, goal-fit, FSA-style, or WHO-style details.",
        "- **Knapsack fidelity:** for ordinary recommendation-required cases, a plan exists and its selected role-item IDs exactly match a fresh direct Beacon Knapsack run for the same persona. Missing plans fail; injected-fault cases are excluded.",
        "- **Injected-fault detection:** the checker identifies a plan whose first required meal role was deliberately removed after recommendation.",
        "- **Unsafe release:** an injected faulty plan reaches the response boundary. Lower is better; zero is required.",
        "- **Latency:** wall-clock time for identity resolution, all model turns, and local tool execution.",
        "",
        "## Scope",
        "",
        "The profiles are fictional, and the experiment is a software evaluation rather than clinical validation. FSA-style and WHO-style values are application-defined aggregate proxies computed by the reused Beacon module; they are not official diagnoses or individualized medical advice.",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
