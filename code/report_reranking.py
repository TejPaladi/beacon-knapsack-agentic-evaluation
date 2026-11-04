"""Build the checked report for Experiment 7 (constrained hybrid reranking).

Expected layout under ``--results-dir``::

    default.json
    rules.json
    model__<model>__r<repetition>.json

Model conditions are summarized per repetition and by a per-case majority;
H7a-H7c are evaluated with the criteria in ``docs/reranking_experiment.md``.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from report_hard_wording import modal
    from report_meaningful_tools import counts, mcnemar_exact, pct, wilson
    from rule_reranker import detect
except ModuleNotFoundError:
    from code.report_hard_wording import modal
    from code.report_meaningful_tools import counts, mcnemar_exact, pct, wilson
    from code.rule_reranker import detect


LABELS = {"default": "Knapsack default", "rules": "Keyword reranker"}
SHARED = ("dataset_sha256", "system_prompt_sha256", "rule_reranker_sha256", "candidates_sha256", "repository_commit")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect(results_dir: Path) -> dict[str, dict[int, dict[str, Any]]]:
    conditions = {LABELS[name]: {1: load(results_dir / f"{name}.json")} for name in LABELS}
    models: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for path in sorted(results_dir.glob("model__*__r*.json")):
        result = load(path)
        models[result["provenance"]["model"]][int(result["provenance"]["repetition"])] = result
    conditions.update(dict(sorted(models.items())))
    return conditions


def validate(conditions: dict[str, dict[int, dict[str, Any]]]) -> None:
    every = [run for reps in conditions.values() for run in reps.values()]
    for field in SHARED:
        if len({run["provenance"].get(field) for run in every}) != 1:
            raise ValueError(f"Results do not share one {field}.")
    if any(run["provenance"].get("worktree_dirty") for run in every):
        raise ValueError("At least one run used an uncommitted worktree.")
    if {run["summary"]["cases"] for run in every} != {48}:
        raise ValueError("Every result must contain 48 cases.")


def per_case(reps: dict[int, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for repetition in sorted(reps):
        for case in reps[repetition]["cases"]:
            by_case[case["case_id"]].append(case)
    return {
        case_id: {
            "wording": cases[0]["wording"],
            "default_is_best": cases[0]["default_is_best"],
            "chosen": modal([c["chosen"] for c in cases]),
            "satisfied": sum(c["satisfied"] for c in cases) * 2 > len(cases),
            "stable": len({c["chosen"] for c in cases}) == 1,
            "request": cases[0]["request"],
            "best": cases[0]["best_candidates"],
        }
        for case_id, cases in by_case.items()
    }


def condition_rows(conditions: dict[str, dict[int, dict[str, Any]]]) -> list[str]:
    lines = [
        "| Condition | Satisfied (48) | 95% CI | Explicit (24) | Implicit (24) | Default not best | Hard violations | Mean latency (ms) |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, reps in conditions.items():
        summaries = [reps[r]["summary"] for r in sorted(reps)]
        majority = per_case(reps)
        satisfied = sum(v["satisfied"] for v in majority.values())
        low, high = wilson(satisfied, 48)
        open_total = summaries[0]["non_default_cases"]
        lines.append(
            f"| {name} | {counts([s['satisfied'] for s in summaries])} | {pct(low)}–{pct(high)} | "
            f"{counts([s['explicit_satisfied'] for s in summaries])} | {counts([s['implicit_satisfied'] for s in summaries])} | "
            f"{counts([s['non_default_satisfied'] for s in summaries])}/{open_total} | "
            f"{counts([s['hard_violations'] for s in summaries])} | "
            f"{sum(s['mean_latency_ms'] for s in summaries) / len(summaries):.1f} |"
        )
    return lines


def hypothesis_lines(conditions: dict[str, dict[int, dict[str, Any]]]) -> list[str]:
    rules = per_case(conditions[LABELS["rules"]])
    models = [name for name in conditions if name not in LABELS.values()]
    majorities = {m: per_case(conditions[m]) for m in models}

    def satisfied(values: dict[str, dict[str, Any]], wording: str) -> set[str]:
        return {cid for cid, v in values.items() if v["wording"] == wording and v["satisfied"]}

    best = max(models, key=lambda m: len(satisfied(majorities[m], "implicit")))
    model_implicit, rule_implicit = satisfied(majorities[best], "implicit"), satisfied(rules, "implicit")
    only_model, only_rules = len(model_implicit - rule_implicit), len(rule_implicit - model_implicit)
    p_value = mcnemar_exact(only_model, only_rules)
    h7a = len(model_implicit) > len(rule_implicit) and p_value < 0.05

    best_explicit = max(models, key=lambda m: len(satisfied(majorities[m], "explicit")))
    model_explicit = len(satisfied(majorities[best_explicit], "explicit"))
    rule_explicit = len(satisfied(rules, "explicit"))
    h7b = rule_explicit >= model_explicit

    violations = sum(run["summary"]["hard_violations"] for reps in conditions.values() for run in reps.values())
    h7c = violations == 0

    def verdict(flag: bool) -> str:
        return "**Supported.**" if flag else "**Not supported.**"

    return [
        f"- **H7a** (best model beats the keyword reranker on implicit wording): {verdict(h7a)} "
        f"`{best}` satisfies {len(model_implicit)}/24 implicit requests and the keyword reranker "
        f"{len(rule_implicit)}/24; {only_model} only by the model and {only_rules} only by the rules "
        f"(exact McNemar p = {p_value:.3g}).",
        f"- **H7b** (keyword reranker at least matches the best model on explicit wording): {verdict(h7b)} "
        f"Keyword reranker {rule_explicit}/24; best model (`{best_explicit}`) {model_explicit}/24.",
        f"- **H7c** (every chosen plan passes validation): {verdict(h7c)} {violations} hard violations "
        "across all conditions and repetitions.",
    ]


def fallback_rows(conditions: dict[str, dict[int, dict[str, Any]]]) -> list[str]:
    """Exploratory: the keyword reranker when it detects a cue, otherwise the model."""

    rules = per_case(conditions[LABELS["rules"]])
    no_cue = {cid for cid, v in rules.items() if detect(v["request"]) is None}
    lines = [
        f"The keyword reranker detects no cue in {len(no_cue)} requests and then keeps the Knapsack default.",
        "",
        "| Model | Satisfied (48) | Implicit (24) | Model satisfied on no-cue requests |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, reps in conditions.items():
        if name in LABELS.values():
            continue
        model = per_case(reps)
        chosen = {cid: (model if cid in no_cue else rules)[cid] for cid in rules}
        implicit = sum(v["satisfied"] for v in chosen.values() if v["wording"] == "implicit")
        lines.append(
            f"| {name} | {sum(v['satisfied'] for v in chosen.values())} | {implicit} | "
            f"{sum(model[cid]['satisfied'] for cid in no_cue)}/{len(no_cue)} |"
        )
    return lines


def miss_rows(conditions: dict[str, dict[int, dict[str, Any]]]) -> list[str]:
    lines = ["| Condition | Request | Wording | Chose | Best |", "| --- | --- | --- | ---: | --- |"]
    for name, reps in conditions.items():
        if name == LABELS["default"]:
            continue
        for value in per_case(reps).values():
            if not value["satisfied"]:
                lines.append(
                    f"| {name} | {value['request']} | {value['wording']} | {value['chosen']} | "
                    f"{', '.join(map(str, value['best']))} |"
                )
    return lines if len(lines) > 2 else ["Every request was satisfied."]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    conditions = collect(args.results_dir)
    validate(conditions)
    first = conditions[LABELS["default"]][1]
    candidate_counts = ", ".join(f"{pid} {len(c)}" for pid, c in first["candidates"].items())
    models = [n for n in conditions if n not in LABELS.values()]
    stability = "; ".join(
        f"`{m}` {sum(v['stable'] for v in per_case(conditions[m]).values())}/48" for m in models
    )
    lines = [
        "# Experiment 7: constrained hybrid reranking",
        "",
        "Beacon Knapsack proposes several distinct day-plans per persona, all of which pass validation. A selector picks one for a stated preference about protein, calories, fiber, or carbohydrates, worded explicitly or as a goal. A choice satisfies the request when its total for that nutrient is the best among the candidates.",
        "",
        f"- Repository commit: `{first['provenance']['repository_commit']}`; Beacon backend commit: `{first['provenance']['beacon_backend_commit']}`.",
        f"- Distinct candidates per persona: {candidate_counts}.",
        f"- Same choice in every repetition: {stability}.",
        "",
        "## Results",
        "",
        *condition_rows(conditions),
        "",
        "Counts show one number when repetitions agree and every repetition otherwise. \"Default not best\" counts satisfied requests among those where Knapsack's default plan is not already a best candidate, where a reranker can add value.",
        "",
        "## Hypotheses (per-case majority)",
        "",
        *hypothesis_lines(conditions),
        "",
        "## Exploratory: keyword reranker with a model fallback (per-case majority)",
        "",
        "This combination was defined after the results were seen, so it is not a test of H7.",
        "",
        *fallback_rows(conditions),
        "",
        "## Unsatisfied requests (per-case majority)",
        "",
        *miss_rows(conditions),
        "",
        "## Scope",
        "",
        "Every candidate comes from Knapsack and passes validation, so safety holds by construction; the experiment measures whether a selector maps a stated preference to the right nutrient and direction. Personas with identical dietary constraints share candidate sets. The requests and the keyword reranker were written by the same authors, with the reranker committed first.",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
