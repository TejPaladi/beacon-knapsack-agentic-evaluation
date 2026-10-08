"""Create a compact, honest Knapsack-versus-agentic comparison report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_result(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def score(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def milliseconds(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def persona_ids(result: dict[str, Any] | None) -> set[str]:
    return {str(case["persona_id"]) for case in (result or {}).get("cases", [])}


def comparable_full_evaluation(
    direct: dict[str, Any] | None, agentic: dict[str, Any] | None
) -> bool:
    """A comparison needs the same complete six-persona case set in both runs."""

    if direct is None or agentic is None:
        return False
    direct_ids = persona_ids(direct)
    agentic_ids = persona_ids(agentic)
    return bool(direct_ids) and direct_ids == agentic_ids and len(direct_ids) == 6


def quality_value(case: dict[str, Any], section: str, field: str) -> float | None:
    value = ((case.get("quality_evaluation") or {}).get(section) or {}).get(field)
    return float(value) if isinstance(value, (int, float)) else None


def row(label: str, result: dict[str, Any] | None, agentic: bool) -> str:
    if result is None:
        return f"| {label} | not run | — | — | — | — | — | — | — | — | — | — |"
    summary = result["summary"]
    return (
        "| {label} | {completed}/{cases} ({status}) | {coverage} | {fidelity} | "
        "{sequence} | {goodness} | {quality} | {nutrition} | {latency} | "
        "{rate_retries} | {format_retries} | {failures} |"
    ).format(
        label=label,
        completed=summary["completed_cases"],
        cases=summary["cases"],
        status=summary["status"],
        coverage=percent(summary["role_coverage_rate"]),
        fidelity=percent(summary["knapsack_fidelity_rate"]),
        sequence=percent(summary["tool_sequence_rate"]) if agentic else "N/A",
        goodness=score(summary.get("mean_legacy_goodness")),
        quality=score(summary.get("mean_beacon_quality_score")),
        nutrition=score(summary.get("mean_nutrition_goal_fit")),
        latency=milliseconds(summary["mean_latency_ms"]),
        rate_retries=summary.get("total_rate_limit_retries", "N/A") if agentic else "N/A",
        format_retries=summary.get("total_tool_format_retries", "N/A") if agentic else "N/A",
        failures=summary["api_or_timeout_failures"],
    )


def agent_case_rows(result: dict[str, Any] | None) -> list[str]:
    if result is None:
        return []
    rows = []
    for case in result.get("cases", []):
        status = "complete" if not case.get("api_error") else "provider failure"
        raw_failure = str(case.get("api_error") or "")
        if "HTTP 429" in raw_failure:
            failure = "Groq HTTP 429 rate limit"
        elif raw_failure:
            failure = raw_failure.replace("|", "\\|")[:160]
        else:
            failure = "—"
        rows.append(
            (
                "| {name} (`{persona_id}`) | {status} | {coverage} | {fidelity} | "
                "{sequence} | {goodness} | {quality} | {nutrition} | {latency} | "
                "{rate_retries} | {format_retries} | {failure} |"
            ).format(
                name=case.get("persona_name", "Unknown"),
                persona_id=case.get("persona_id", "—"),
                status=status,
                coverage="pass" if case.get("valid_role_coverage") else "fail",
                fidelity="pass" if case.get("matches_direct_knapsack") else "fail",
                sequence="pass" if case.get("tool_sequence_valid") else "fail",
                goodness=score(quality_value(case, "legacy_goodness", "score")),
                quality=score(quality_value(case, "quality", "quality_score")),
                nutrition=score(
                    quality_value(case, "nutrition_goal_adherence", "mean_fit")
                ),
                latency=milliseconds(case.get("latency_ms")),
                rate_retries=case.get("rate_limit_retries", "—"),
                format_retries=case.get("tool_format_retries", "—"),
                failure=failure,
            )
        )
    return rows


def nutrient_text(case: dict[str, Any], nutrient: str, unit: str) -> str:
    adherence = (case.get("quality_evaluation") or {}).get(
        "nutrition_goal_adherence"
    ) or {}
    actual = (adherence.get("actual_totals") or {}).get(nutrient)
    goal = (adherence.get("goals") or {}).get(nutrient)
    fit = (adherence.get("per_nutrient_fit") or {}).get(nutrient)
    if not all(isinstance(value, (int, float)) for value in (actual, goal, fit)):
        return "—"
    return f"{actual:.1f}/{goal:.1f} {unit} ({fit:.3f})"


def nutrition_rows(result: dict[str, Any] | None) -> list[str]:
    if result is None:
        return []
    rows = []
    for case in result.get("cases", []):
        rows.append(
            "| {name} (`{persona_id}`) | {calories} | {carbs} | {protein} | {fiber} | {mean_fit} |".format(
                name=case.get("persona_name", "Unknown"),
                persona_id=case.get("persona_id", "—"),
                calories=nutrient_text(case, "calories", "kcal"),
                carbs=nutrient_text(case, "carbs", "g"),
                protein=nutrient_text(case, "protein", "g"),
                fiber=nutrient_text(case, "fiber", "g"),
                mean_fit=score(
                    quality_value(case, "nutrition_goal_adherence", "mean_fit")
                ),
            )
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct", type=Path, required=True)
    parser.add_argument("--agentic", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    direct = load_result(args.direct)
    agentic = load_result(args.agentic)
    full_pair = comparable_full_evaluation(direct, agentic)
    agentic_label = "Agentic Knapsack" if full_pair else "Agentic Knapsack (pilot / not comparable)"

    if agentic is None:
        run_note = "Agentic Knapsack has not been run yet."
    elif full_pair:
        run_note = "Run status: **full comparison**. Both conditions contain the same six personas."
    else:
        run_note = (
            "Run status: **pilot only**. The agentic run does not contain the same complete "
            "six-persona case set as the direct run, so do not compare its aggregate rate to the direct baseline."
        )

    lines = [
        "# Beacon Knapsack: Direct vs. Agentic Orchestration",
        "",
        "Both conditions use the same six stored Beacon personas, all local Beacon catalog sources, and Beacon's existing Knapsack pipeline. The agent is not allowed to choose food; it must retrieve the profile and invoke Knapsack.",
        "",
        run_note,
        "",
        "| Condition | Completed cases | Requested-role coverage | Exact Knapsack output fidelity | Required tool sequence | Original goodness | Beacon quality score | Nutrition-goal fit | Mean end-to-end latency (ms) | Rate-limit retries | Tool-JSON retries | Provider/timeout failures |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        row("Beacon+ direct Knapsack", direct, agentic=False),
        row(agentic_label, agentic, agentic=True),
        "",
        "Original goodness is Beacon's original equal-weight average of meal variety, requested-role coverage, and preference-constraint scores. Beacon quality score is the newer weighted evaluator. Nutrition-goal fit is its 0–1 nutrition component: daily calorie, carbohydrate, protein, and fiber totals are compared with the stored goals.",
        "",
        "Interpretation: direct Knapsack is the deterministic reference. Agentic Knapsack is successful only when it selects the intended persona, retrieves that profile, calls Knapsack, and returns exactly the corresponding Knapsack plan. A lower agentic score measures orchestration failures or API failures, not a change in the deterministic recommendation.",
        "",
        "Scope: the nutrition-goal metrics are evaluated *after* plan generation. The current Knapsack selector does not use numeric nutrition goals as optimization constraints, so these metrics report observed goal fit rather than proof that the selector optimized those goals.",
        "",
        "Terminology note: `m6` is only the internal Beacon source identifier for this traditional Knapsack implementation; this experiment calls the recommender Knapsack.",
    ]
    if agentic is not None and agentic["summary"].get("total_rate_limit_retries", 0):
        lines.extend(
            [
                "",
                "Rate-limit note: end-to-end agent latency includes provider-imposed retry waits. "
                "The run recorded {retries} retries / {wait:.1f}s total waiting; mean latency excluding "
                "that wait was {latency} ms.".format(
                    retries=agentic["summary"]["total_rate_limit_retries"],
                    wait=agentic["summary"]["total_rate_limit_wait_seconds"],
                    latency=milliseconds(
                        agentic["summary"].get("mean_latency_excluding_rate_limit_wait_ms")
                    ),
                ),
            ]
        )
    if agentic is not None:
        lines.extend(
            [
                "",
                "## Agentic case audit",
                "",
                "| Persona | Run status | Role coverage | Exact Knapsack fidelity | Required tool sequence | Original goodness | Beacon quality | Nutrition fit | Latency (ms) | Rate retries | Tool-JSON retries | Provider failure |",
                "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
                *agent_case_rows(agentic),
                "",
                "## Nutrition-goal audit (agentic observed plans)",
                "",
                "Each entry is `actual/goal (fit)`; fit is 1.000 for an exact daily match and declines linearly with absolute deviation.",
                "",
                "| Persona | Calories | Carbs | Protein | Fiber | Mean nutrition fit |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
                *nutrition_rows(agentic),
            ]
        )
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
