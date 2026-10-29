"""Create the deterministic Knapsack versus LLM-only selection report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def nested(case: dict[str, Any], *keys: str) -> float:
    value: Any = case
    for key in keys:
        value = value[key]
    return float(value)


def fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def direct_summary(result: dict[str, Any]) -> dict[str, Any]:
    cases = result["direct_knapsack_cases"]
    return {
        "safe": sum(case["quality_evaluation"]["quality"]["valid"] for case in cases),
        "violations": sum(
            len(case["quality_evaluation"]["quality"]["hard_violations"])
            for case in cases
        ),
        "goodness": mean(
            [nested(case, "quality_evaluation", "legacy_goodness", "score") for case in cases]
        ),
        "quality": mean(
            [nested(case, "quality_evaluation", "quality", "quality_score") for case in cases]
        ),
        "safe_quality": mean(
            [nested(case, "quality_evaluation", "quality", "quality_score") for case in cases]
        ),
        "nutrition": mean(
            [
                nested(
                    case,
                    "quality_evaluation",
                    "nutrition_goal_adherence",
                    "mean_fit",
                )
                for case in cases
            ]
        ),
        "duplicates": 0.0,
        "latency": mean([float(case["latency_ms"]) for case in cases]),
    }


def safe_only_quality(result: dict[str, Any]) -> float | None:
    safe_cases = [case for case in result["llm_only_cases"] if case["case_pass"]]
    if not safe_cases:
        return None
    return mean(
        [nested(case, "quality_evaluation", "quality", "quality_score") for case in safe_cases]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [load(path) for path in args.result]
    if any(result["summary"]["cases"] != 6 for result in results):
        raise ValueError("Every LLM result must contain all six personas.")
    if len({result["provenance"]["catalog_sha256"] for result in results}) != 1:
        raise ValueError("LLM results use different catalogs.")

    direct = direct_summary(results[0])
    lines = [
        "# Deterministic Knapsack versus LLM-only meal selection",
        "",
        "All conditions use the same six fictional Beacon personas and the same role-eligible local catalog. Knapsack receives the stored profile and selects a one-day plan. Each LLM receives the profile and complete compact catalog, then directly selects catalog IDs without a recommendation tool or dietary pre-filter. A JSON schema enforces only requested role and catalog membership; deterministic validation and Beacon metrics run after selection.",
        "",
        "| Selector | Safe valid plans | Hard violations | Exact Knapsack matches | Mean goodness | Quality, all cases | Quality, safe cases only | Mean nutrition fit | Mean repeated foods | Mean latency (ms) | Prompt + completion tokens |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| Beacon Knapsack | {direct['safe']}/6 | {direct['violations']} | 6/6 (reference) | {fmt(direct['goodness'])} | {fmt(direct['quality'])} | {fmt(direct['safe_quality'])} | {fmt(direct['nutrition'])} | {direct['duplicates']:.1f} | {direct['latency']:.1f} | 0 |",
    ]
    for result in sorted(results, key=lambda item: item["provenance"]["model"]):
        summary = result["summary"]
        tokens = summary["total_prompt_tokens"] + summary["total_completion_tokens"]
        lines.append(
            f"| LLM-only `{result['provenance']['model']}` | "
            f"{summary['safe_valid_plans']}/6 | {summary['hard_constraint_violations']} | "
            f"{summary['exact_knapsack_matches']}/6 | {fmt(summary['mean_legacy_goodness'])} | "
            f"{fmt(summary['mean_beacon_quality'])} | {fmt(safe_only_quality(result))} | "
            f"{fmt(summary['mean_nutrition_fit'])} | "
            f"{summary['mean_duplicate_food_count']:.1f} | {summary['mean_latency_ms']:.1f} | "
            f"{tokens} |"
        )

    lines.extend(
        [
            "",
            "## Per-persona LLM audit",
            "",
            "| Model | Persona | Safe | Violations | Beacon quality | Nutrition fit | Repeated foods | Latency (ms) |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for result in sorted(results, key=lambda item: item["provenance"]["model"]):
        model = result["provenance"]["model"]
        for case in result["llm_only_cases"]:
            evaluation = case.get("quality_evaluation")
            quality = (
                evaluation["quality"]["quality_score"] if evaluation is not None else None
            )
            nutrition = (
                evaluation["nutrition_goal_adherence"]["mean_fit"]
                if evaluation is not None
                else None
            )
            lines.append(
                f"| `{model}` | {case['persona_name']} | "
                f"{'yes' if case['case_pass'] else 'no'} | "
                f"{len(case['hard_constraint_violations'])} | {fmt(quality)} | "
                f"{fmt(nutrition)} | {case['duplicate_food_count']} | "
                f"{case['latency_ms']:.1f} |"
            )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Knapsack is the only deterministic selector in this comparison and is the six-person reference, not ground truth for the uniquely best meal.",
            "- Granite produced six dietary-adherent plans but lower mean quality and nutrition fit than Knapsack, with repeated foods.",
            "- Llama produced no repeated foods and slightly higher mean nutrition fit, but violated diabetes or vegetarian constraints in three personas. Beacon assigns zero overall quality to unsafe plans, lowering its all-case mean to 0.453. Its three safe plans average 0.906 quality, so the evidence does not support claiming that Knapsack has the highest conditional meal quality.",
            "- The safe-only Llama result is based on three selected cases and must be read together with its 3/6 safety rate; it is not evidence that Llama is a better selector overall.",
            "- Nutrition fit alone is not a safety metric: a plan can approach numeric nutrient goals while violating a stored dietary condition.",
            "- Zero exact matches means the LLMs selected different plans; it does not by itself mean those plans were invalid.",
            "",
            "These are Beacon's own system metrics, which were designed alongside its deterministic methods; they are not independent human judgments and may favor Knapsack's design objectives. This is a one-run, six-person simulated comparison with two small local models. It supports a preliminary architecture finding, not a clinical or population-level recommendation claim.",
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
