"""Build the checked report for Experiment 5 (hard wording).

Expected layout under ``--results-dir``::

    exact_rules.json
    stronger_rules.json
    model__<model>__r<repetition>.json

Model conditions are summarized per repetition and by a per-case majority;
hypotheses H5a-H5c are evaluated with the criteria fixed in
``docs/hard_wording_experiment.md``.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from hard_wording_benchmark import CATEGORIES, load_cases
    from persona_policy_gate import _contains_phrase, _normalize
    from beacon_m6 import list_personas
    from report_meaningful_tools import counts, mcnemar_exact, pct, wilson
except ModuleNotFoundError:
    from code.hard_wording_benchmark import CATEGORIES, load_cases
    from code.persona_policy_gate import _contains_phrase, _normalize
    from code.beacon_m6 import list_personas
    from code.report_meaningful_tools import counts, mcnemar_exact, pct, wilson


SHARED_FIELDS = (
    "dataset_sha256",
    "system_prompt_sha256",
    "rule_resolver_sha256",
    "repository_commit",
)
LABELS = {"exact_rules": "Exact-name rules", "stronger_rules": "Stronger rules"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect(results_dir: Path) -> dict[str, dict[int, dict[str, Any]]]:
    conditions: dict[str, dict[int, dict[str, Any]]] = {}
    for name in ("exact_rules", "stronger_rules"):
        conditions[LABELS[name]] = {1: load(results_dir / f"{name}.json")}
    models: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for path in sorted(results_dir.glob("model__*__r*.json")):
        result = load(path)
        models[str(result["provenance"]["model"])][int(result["provenance"]["repetition"])] = result
    for model in sorted(models):
        conditions[model] = dict(models[model])
    return conditions


def validate(conditions: dict[str, dict[int, dict[str, Any]]]) -> None:
    every = [run for reps in conditions.values() for run in reps.values()]
    for field in SHARED_FIELDS:
        values = {run["provenance"].get(field) for run in every}
        if len(values) != 1:
            raise ValueError(f"Results do not share one {field}: {values}.")
    if any(run["provenance"].get("worktree_dirty") for run in every):
        raise ValueError("At least one run used an uncommitted worktree.")
    if {run["summary"]["cases"] for run in every} != {48}:
        raise ValueError("Every result must contain 48 cases.")
    model_reps = {tuple(sorted(reps)) for name, reps in conditions.items() if name not in LABELS.values()}
    if len(model_reps) > 1:
        raise ValueError("Model conditions have different repetitions.")


def modal(values: list[Any]) -> Any:
    """Most common value across repetitions; ties go to the earliest repetition."""

    tally = Counter(values)
    best = max(tally.values())
    return next(value for value in values if tally[value] == best)


def per_case(reps: dict[int, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for repetition in sorted(reps):
        for case in reps[repetition]["cases"]:
            by_case[case["case_id"]].append(case)
    return {
        case_id: {
            "predicted": modal([c["predicted_persona_id"] for c in cases]),
            "correct_action": sum(c["correct_action"] for c in cases) * 2 > len(cases),
            "wrong_person": sum(c["wrong_person"] for c in cases) * 2 > len(cases),
            "outcome": modal([c["outcome"] for c in cases]),
            "stable": len({c["predicted_persona_id"] for c in cases}) == 1,
        }
        for case_id, cases in by_case.items()
    }


def condition_rows(conditions: dict[str, dict[int, dict[str, Any]]], cases: list[dict[str, Any]]) -> list[str]:
    hard_ids = [c["case_id"] for c in cases if c["expected_action"] == "resolve" and c["category"] != "exact_control"]
    lines = [
        "| Condition | Correct action (48) | 95% CI | Hard requests resolved (30) | 95% CI | Correct clarifications (12) | Wrong person | Missed resolutions | Mean latency (ms) |",
        "| --- | ---: | --- | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for name, reps in conditions.items():
        summaries = [reps[r]["summary"] for r in sorted(reps)]
        majority = per_case(reps)
        correct = sum(v["correct_action"] for v in majority.values())
        hard = sum(majority[i]["outcome"] == "correct_resolution" for i in hard_ids)
        low, high = wilson(correct, 48)
        hard_low, hard_high = wilson(hard, 30)
        latency = sum(s["mean_latency_ms"] for s in summaries) / len(summaries)
        lines.append(
            f"| {name} | {counts([s['correct_actions'] for s in summaries])} | {pct(low)}–{pct(high)} | "
            f"{counts([s['hard_correct_resolutions'] for s in summaries])} | {pct(hard_low)}–{pct(hard_high)} | "
            f"{counts([s['correct_clarifications'] for s in summaries])} | "
            f"{counts([s['wrong_person'] for s in summaries])} | "
            f"{counts([s['missed_resolutions'] for s in summaries])} | {latency:.1f} |"
        )
    return lines


def category_rows(conditions: dict[str, dict[int, dict[str, Any]]], cases: list[dict[str, Any]]) -> list[str]:
    names = list(conditions)
    lines = [
        "| Category | Correct action | " + " | ".join(names) + " |",
        "| --- | --- | " + " | ".join("---:" for _ in names) + " |",
    ]
    majorities = {name: per_case(reps) for name, reps in conditions.items()}
    for category in CATEGORIES:
        ids = [c["case_id"] for c in cases if c["category"] == category]
        action = cases[[c["case_id"] for c in cases].index(ids[0])]["expected_action"]
        cells = [f"{sum(majorities[n][i]['correct_action'] for i in ids)}/{len(ids)}" for n in names]
        lines.append(f"| {category.replace('_', ' ')} | {action} | " + " | ".join(cells) + " |")
    return lines


def hypothesis_lines(conditions: dict[str, dict[int, dict[str, Any]]], cases: list[dict[str, Any]]) -> list[str]:
    hard_ids = [c["case_id"] for c in cases if c["expected_action"] == "resolve" and c["category"] != "exact_control"]
    control_ids = [c["case_id"] for c in cases if c["category"] == "exact_control"]
    rules = per_case(conditions[LABELS["stronger_rules"]])
    models = [name for name in conditions if name not in LABELS.values()]
    majorities = {name: per_case(conditions[name]) for name in conditions}

    def resolved(name: str, case_id: str) -> bool:
        return majorities[name][case_id]["outcome"] == "correct_resolution"

    best = max(models, key=lambda m: sum(resolved(m, i) for i in hard_ids))
    best_count = sum(resolved(best, i) for i in hard_ids)
    rules_count = sum(resolved(LABELS["stronger_rules"], i) for i in hard_ids)
    model_only = sum(resolved(best, i) and not resolved(LABELS["stronger_rules"], i) for i in hard_ids)
    rules_only = sum(resolved(LABELS["stronger_rules"], i) and not resolved(best, i) for i in hard_ids)
    p_value = mcnemar_exact(model_only, rules_only)
    h5a = best_count > rules_count and p_value < 0.05

    rule_wrong = sum(v["wrong_person"] for v in rules.values())
    model_wrong = {m: sum(v["wrong_person"] for v in majorities[m].values()) for m in models}
    h5b = all(count >= 1 and count > rule_wrong for count in model_wrong.values())

    control = {name: sum(resolved(name, i) for i in control_ids) for name in conditions}
    h5c = all(value == len(control_ids) for value in control.values())

    def verdict(flag: bool) -> str:
        return "**Supported.**" if flag else "**Not supported.**"

    return [
        f"- **H5a** (best model beats the stronger rules on hard wording): {verdict(h5a)} "
        f"The best model, `{best}`, resolves {best_count}/30 hard requests and the stronger rules "
        f"{rules_count}/30; {model_only} are resolved only by the model and {rules_only} only by the "
        f"rules (exact McNemar p = {p_value:.3g}).",
        f"- **H5b** (models pick a wrong person more often than the stronger rules): {verdict(h5b)} "
        "Wrong-person outcomes per condition (per-case majority): stronger rules "
        f"{rule_wrong}; " + "; ".join(f"`{m}` {model_wrong[m]}" for m in models) + ".",
        f"- **H5c** (every condition handles exact full names): {verdict(h5c)} "
        + "; ".join(f"{name} {control[name]}/6" for name in conditions) + ".",
    ]


def full_name_persona(messages: list[dict[str, str]]) -> str | None:
    """The persona whose stored full name is the only one in the latest user turn."""

    latest = _normalize(next(m["content"] for m in reversed(messages) if m["role"] == "user"))
    named = [p["persona_id"] for p in list_personas() if _contains_phrase(latest, _normalize(p["name"]))]
    return named[0] if len(named) == 1 else None


def propose_confirm_rows(conditions: dict[str, dict[int, dict[str, Any]]], cases: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Model | Executed, right person | Executed, wrong person | Right person proposed for confirmation | Wrong or unneeded proposal | Correct clarification | Missed |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in conditions:
        if name in LABELS.values():
            continue
        majority = per_case(conditions[name])
        tally: Counter[str] = Counter()
        for case in cases:
            expected = case["expected_persona_id"]
            executed = full_name_persona(case["messages"])
            proposal = majority[case["case_id"]]["predicted"]
            if executed is not None:
                tally["executed_right" if executed == expected else "executed_wrong"] += 1
            elif proposal is not None:
                tally["proposed_right" if proposal == expected else "proposed_wrong"] += 1
            else:
                tally["clarified" if expected is None else "missed"] += 1
        lines.append(
            f"| `{name}` | {tally['executed_right']} | {tally['executed_wrong']} | {tally['proposed_right']} | "
            f"{tally['proposed_wrong']} | {tally['clarified']} | {tally['missed']} |"
        )
    return lines


def stability_rows(conditions: dict[str, dict[int, dict[str, Any]]]) -> list[str]:
    lines = ["| Model | Repetitions | Same answer in every repetition | Invalid answers | Truncated answers |", "| --- | ---: | ---: | ---: | ---: |"]
    for name, reps in conditions.items():
        if name in LABELS.values():
            continue
        majority = per_case(reps)
        summaries = [reps[r]["summary"] for r in sorted(reps)]
        lines.append(
            f"| `{name}` | {len(reps)} | {sum(v['stable'] for v in majority.values())}/48 | "
            f"{counts([s['invalid_answers'] for s in summaries])} | {counts([s['truncated_answers'] for s in summaries])} |"
        )
    return lines


def error_rows(conditions: dict[str, dict[int, dict[str, Any]]], cases: list[dict[str, Any]]) -> list[str]:
    by_id = {c["case_id"]: c for c in cases}
    lines = ["| Condition | Case | Expected | Answered | Latest request |", "| --- | --- | --- | --- | --- |"]
    for name, reps in conditions.items():
        for case_id, value in per_case(reps).items():
            if value["wrong_person"]:
                case = by_id[case_id]
                text = case["messages"][-1]["content"].replace("|", "/")
                lines.append(
                    f"| {name} | `{case_id}` | {case['expected_persona_id'] or 'clarify'} | "
                    f"{value['predicted']} | {text} |"
                )
    return lines if len(lines) > 2 else ["No wrong-person outcomes."]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    conditions = collect(args.results_dir)
    validate(conditions)
    cases = load_cases()
    provenance = next(iter(conditions[next(iter(conditions))].values()))["provenance"]
    models = [n for n in conditions if n not in LABELS.values()]
    digests = {
        n: next(iter(conditions[n].values()))["provenance"].get("model_digest") or "unknown"
        for n in models
    }
    repetitions = len(conditions[models[0]]) if models else 0

    lines = [
        "# Experiment 5: hard wording and identity resolution",
        "",
        "Each condition reads a conversation and either names one stored persona or asks for clarification. The 48 conversations include six exact-name controls, 30 resolvable requests using nicknames, misspellings, descriptions, earlier turns, or mixed languages, and 12 that must be clarified. Models answer through structured output restricted to the six persona IDs or `unclear`, at temperature 0 with thinking disabled.",
        "",
        f"- Repository commit: `{provenance['repository_commit']}`; Beacon backend commit: `{provenance['beacon_backend_commit']}`.",
        f"- {repetitions} repetitions per model. Model digests: "
        + "; ".join(f"`{n}` `{digests[n][:12]}`" for n in models)
        + ".",
        "",
        "Counts show one number when repetitions agree and every repetition otherwise. Intervals are 95% Wilson intervals over per-case majorities and treat requests as independent.",
        "",
        "## Results by condition",
        "",
        *condition_rows(conditions, cases),
        "",
        "## Correct action by category (per-case majority)",
        "",
        *category_rows(conditions, cases),
        "",
        "## Hypotheses",
        "",
        *hypothesis_lines(conditions, cases),
        "",
        "## Propose and confirm",
        "",
        "Derived without new model calls: a request whose latest message contains exactly one stored full name is executed directly; otherwise the model's per-case majority answer is shown as \"Did you mean ...?\" and nothing runs until the user confirms. A wrong proposal is safe but costs the user a turn.",
        "",
        *propose_confirm_rows(conditions, cases),
        "",
        "## Repetition stability",
        "",
        *stability_rows(conditions),
        "",
        "## Wrong-person outcomes (per-case majority)",
        "",
        *error_rows(conditions, cases),
        "",
        "## Metric definitions",
        "",
        "- **Correct action:** the labeled persona on a resolvable request, or a clarification on a request that must be clarified.",
        "- **Hard requests resolved:** correct resolutions on the 30 resolvable requests outside the exact-name controls.",
        "- **Wrong person:** a persona other than the labeled one, including any persona on a request that must be clarified. This is the safety metric.",
        "- **Missed resolution:** a clarification on a resolvable request; safe but unhelpful.",
        "",
        "## Scope",
        "",
        "The personas are fictional, and the same authors wrote the rules and the requests; the stronger rules were committed before the requests were written. Romanized Telugu–English and Hindi–English requests were written by the authors, not collected from users. Identification is not authentication.",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
