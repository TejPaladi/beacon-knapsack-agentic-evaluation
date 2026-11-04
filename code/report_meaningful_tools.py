"""Build the checked report for the meaningful-tool experiment.

Expected layout under ``--results-dir``::

    <dataset>/deterministic_pipeline.json
    <dataset>/<architecture>__<model>__r<repetition>.json

where ``<dataset>`` is ``development`` or ``heldout``. Repeated runs are
summarized per repetition and by a per-case majority vote; gated and ungated
conditions are compared case by case with an exact McNemar test.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from meaningful_tools_benchmark import is_text_tool_call, reply_state_flags
except ModuleNotFoundError:
    from code.meaningful_tools_benchmark import is_text_tool_call, reply_state_flags


EXPECTED_CASES = 42
HELDOUT_PREFIX = "heldout_"
REPLY_FLAGS = (
    ("validation_claim", "Claims validation that failed or never ran"),
    ("release_claim", "Release claim contradicts state"),
    ("plan_without_knapsack", "Writes a meal plan Knapsack never produced"),
)
DATASETS = ("development", "heldout")
UNGATED = "meaningful_agent_prompt_only"
GATED = "meaningful_agent_gated"
ARCHITECTURE_LABELS = {
    "deterministic_pipeline": "No-LLM rule pipeline",
    UNGATED: "No release gate",
    GATED: "Release gate",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(only_first: int, only_second: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts."""

    n = only_first + only_second
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(only_first, only_second) + 1))
    return min(1.0, 2 * tail / 2**n)


def counts(values: list[int]) -> str:
    """Show one number when repetitions agree, otherwise every repetition."""

    return str(values[0]) if len(set(values)) == 1 else "/".join(map(str, values))


def trace_signature(case: dict[str, Any]) -> list[tuple[str, str, bool]]:
    return [
        (
            str(event["name"]),
            json.dumps(event.get("arguments"), sort_keys=True),
            bool(event.get("ok")),
        )
        for event in case.get("tool_trace", [])
    ]


def gate_prefix_matches(ungated: dict[str, Any], gated: dict[str, Any]) -> bool:
    """True when the gated trace equals the ungated one until the first refusal.

    Once the gate refuses a call, the model sees a different tool result, so
    only the shared prefix is expected to match.
    """

    gated_trace = gated.get("tool_trace", [])
    cut = next(
        (index for index, event in enumerate(gated_trace) if event.get("policy_blocked")),
        None,
    )
    left = trace_signature(ungated)
    right = trace_signature(gated)
    if cut is None:
        return left == right
    return left[:cut] == right[:cut] and len(left) > cut and left[cut][:2] == right[cut][:2]


def collect(results_dir: Path) -> dict[str, dict[str, Any]]:
    data: dict[str, dict[str, Any]] = {}
    for dataset in DATASETS:
        directory = results_dir / dataset
        baseline_path = directory / "deterministic_pipeline.json"
        if not baseline_path.is_file():
            raise ValueError(f"Missing {baseline_path}.")
        runs: dict[tuple[str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
        for path in sorted(directory.glob("*__r*.json")):
            result = load(path)
            provenance = result["provenance"]
            key = (str(provenance["model"]), str(provenance["architecture"]))
            runs[key][int(provenance["repetition"])] = result
        data[dataset] = {"baseline": load(baseline_path), "runs": dict(runs)}
    return data


def validate(data: dict[str, dict[str, Any]]) -> None:
    every = [
        result
        for dataset in data.values()
        for result in [dataset["baseline"]]
        + [run for reps in dataset["runs"].values() for run in reps.values()]
    ]
    for field in (
        "tool_schema_sha256",
        "system_prompt_sha256",
        "repository_commit",
        "beacon_backend_commit",
    ):
        values = {result["provenance"].get(field) for result in every}
        if len(values) != 1:
            raise ValueError(f"Results do not share one {field}: {values}.")
    if any(result["provenance"].get("worktree_dirty") for result in every):
        raise ValueError("At least one run used an uncommitted worktree.")
    if {result["summary"]["cases"] for result in every} != {EXPECTED_CASES}:
        raise ValueError(f"Every final result must contain {EXPECTED_CASES} cases.")
    for name, dataset in data.items():
        hashes = {dataset["baseline"]["provenance"]["dataset_sha256"]} | {
            run["provenance"]["dataset_sha256"]
            for reps in dataset["runs"].values()
            for run in reps.values()
        }
        if len(hashes) != 1:
            raise ValueError(f"{name} results do not share one dataset.")
        models = {model for model, _ in dataset["runs"]}
        repetitions = {tuple(sorted(reps)) for reps in dataset["runs"].values()}
        if len(repetitions) != 1:
            raise ValueError(f"{name} conditions have different repetitions.")
        for model in models:
            if {(model, UNGATED), (model, GATED)} - set(dataset["runs"]):
                raise ValueError(f"{name}/{model} needs both release conditions.")


def majority(reps: dict[int, dict[str, Any]], field: str) -> dict[str, bool]:
    votes: dict[str, list[bool]] = defaultdict(list)
    for run in reps.values():
        for case in run["cases"]:
            votes[case["case_id"]].append(bool(case[field]))
    return {case_id: sum(v) * 2 > len(v) for case_id, v in votes.items()}


def condition_rows(dataset: dict[str, Any]) -> list[str]:
    lines = [
        "| Condition | Strict pass | 95% CI | Correct outcome | 95% CI | Unsafe releases | Unvalidated releases | Gate refusals | Valid tool path | Knapsack fidelity | API/loop failures | Text-only tool calls | Truncated turns | Mean turns | Mean latency (ms) |",
        "| --- | ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def row(name: str, reps: dict[int, dict[str, Any]]) -> str:
        runs = [reps[key] for key in sorted(reps)]
        summaries = [run["summary"] for run in runs]
        strict = majority(reps, "case_pass")
        outcome = majority(reps, "outcome_correct")
        strict_ci = wilson(sum(strict.values()), len(strict))
        outcome_ci = wilson(sum(outcome.values()), len(outcome))
        mean = lambda key: sum(s[key] for s in summaries) / len(summaries)
        turns = [s["mean_agent_turns"] for s in summaries if s.get("mean_agent_turns") is not None]
        turns_text = f"{sum(turns) / len(turns):.2f}" if turns else "—"
        return (
            f"| {name} | {counts([s['passed_cases'] for s in summaries])}/{EXPECTED_CASES} | "
            f"{pct(strict_ci[0])}–{pct(strict_ci[1])} | "
            f"{counts([s['outcome_correct_cases'] for s in summaries])}/{EXPECTED_CASES} | "
            f"{pct(outcome_ci[0])}–{pct(outcome_ci[1])} | "
            f"{counts([s['unsafe_releases'] for s in summaries])} | "
            f"{counts([s['unvalidated_releases'] for s in summaries])} | "
            f"{counts([s['release_blocks'] for s in summaries])} | "
            f"{pct(mean('tool_path_accuracy'))} | {pct(mean('exact_knapsack_fidelity'))} | "
            f"{counts([s['api_or_loop_failures'] for s in summaries])} | "
            f"{counts([sum(is_text_tool_call(c.get('final_text')) for c in run['cases']) for run in runs])} | "
            f"{counts([s.get('truncated_turns', 0) for s in summaries])} | "
            f"{turns_text} | {mean('mean_latency_ms'):.1f} |"
        )

    lines.extend(row(name, reps) for name, reps in conditions(dataset))
    return lines


def paired_rows(dataset: dict[str, Any]) -> list[str]:
    lines = [
        "| Model | Measure | No gate | Gate | Gate only | No gate only | Exact McNemar p |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in sorted({model for model, _ in dataset["runs"]}):
        for field, label in (("outcome_correct", "Correct outcome"), ("case_pass", "Strict pass")):
            ungated = majority(dataset["runs"][(model, UNGATED)], field)
            gated = majority(dataset["runs"][(model, GATED)], field)
            gate_only = sum(gated[c] and not ungated[c] for c in ungated)
            ungated_only = sum(ungated[c] and not gated[c] for c in ungated)
            lines.append(
                f"| {model} | {label} | {sum(ungated.values())} | {sum(gated.values())} | "
                f"{gate_only} | {ungated_only} | {mcnemar_exact(gate_only, ungated_only):.3g} |"
            )
    return lines


def stability_rows(dataset: dict[str, Any]) -> list[str]:
    lines = [
        "| Model | Condition | Repetitions | Identical trace in every repetition | Same strict result in every repetition | Gated trace matches ungated until first refusal |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for (model, architecture), reps in sorted(
        dataset["runs"].items(), key=lambda item: (item[0][0], item[0][1] == GATED)
    ):
        runs = [reps[key] for key in sorted(reps)]
        by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for run in runs:
            for case in run["cases"]:
                by_case[case["case_id"]].append(case)
        identical = sum(
            all(trace_signature(c) == trace_signature(cases[0]) for c in cases)
            for cases in by_case.values()
        )
        same_result = sum(
            len({bool(c["case_pass"]) for c in cases}) == 1 for cases in by_case.values()
        )
        if architecture == GATED:
            ungated = dataset["runs"][(model, UNGATED)]
            matched = total = 0
            for repetition in sorted(reps):
                if repetition not in ungated:
                    continue
                left = {c["case_id"]: c for c in ungated[repetition]["cases"]}
                for case in reps[repetition]["cases"]:
                    total += 1
                    matched += gate_prefix_matches(left[case["case_id"]], case)
            prefix = f"{matched}/{total}"
        else:
            prefix = "—"
        lines.append(
            f"| {model} | {ARCHITECTURE_LABELS[architecture]} | {len(runs)} | "
            f"{identical}/{len(by_case)} | {same_result}/{len(by_case)} | {prefix} |"
        )
    return lines


def category_rows(dataset: dict[str, Any], field: str) -> list[str]:
    columns: list[tuple[str, dict[str, bool]]] = [
        (ARCHITECTURE_LABELS["deterministic_pipeline"], majority({1: dataset["baseline"]}, field))
    ]
    for model in sorted({model for model, _ in dataset["runs"]}):
        for architecture in (UNGATED, GATED):
            columns.append(
                (
                    f"{model} / {ARCHITECTURE_LABELS[architecture]}",
                    majority(dataset["runs"][(model, architecture)], field),
                )
            )
    category_of = {c["case_id"]: c["category"] for c in dataset["baseline"]["cases"]}
    categories = sorted(set(category_of.values()))
    lines = [
        "| Request category | " + " | ".join(name for name, _ in columns) + " |",
        "| --- | " + " | ".join("---:" for _ in columns) + " |",
    ]
    for category in categories:
        ids = [case_id for case_id, cat in category_of.items() if cat == category]
        cells = [f"{sum(votes[i] for i in ids)}/{len(ids)}" for _, votes in columns]
        lines.append(f"| {category.replace('_', ' ')} | " + " | ".join(cells) + " |")
    return lines


def conditions(dataset: dict[str, Any]) -> list[tuple[str, dict[int, dict[str, Any]]]]:
    """Every condition in table order: the rule baseline, then each model."""

    rows = [(ARCHITECTURE_LABELS["deterministic_pipeline"], {1: dataset["baseline"]})]
    for model in sorted({model for model, _ in dataset["runs"]}):
        for architecture in (UNGATED, GATED):
            rows.append(
                (f"{model} / {ARCHITECTURE_LABELS[architecture]}", dataset["runs"][(model, architecture)])
            )
    return rows


def reply_rows(dataset: dict[str, Any]) -> list[str]:
    lines = [
        "| Condition | " + " | ".join(label for _, label in REPLY_FLAGS) + " |",
        "| --- | " + " | ".join("---:" for _ in REPLY_FLAGS) + " |",
    ]
    for name, reps in conditions(dataset):
        runs = [reps[key] for key in sorted(reps)]
        cells = [
            counts([sum(flag in reply_state_flags(case) for case in run["cases"]) for run in runs])
            for flag, _ in REPLY_FLAGS
        ]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


def flagged_replies(data: dict[str, dict[str, Any]]) -> list[str]:
    """List every flagged reply once, with the repetitions that produced it."""

    labels = dict(REPLY_FLAGS)
    lines = []
    for dataset_name in DATASETS:
        for name, reps in conditions(data[dataset_name]):
            found: dict[tuple[str, str], tuple[list[int], str]] = {}
            for repetition in sorted(reps):
                for case in reps[repetition]["cases"]:
                    for flag, evidence in reply_state_flags(case).items():
                        entry = found.setdefault((case["case_id"], flag), ([], evidence))
                        entry[0].append(repetition)
            for (case_id, flag), (repetitions, evidence) in found.items():
                quote = " ".join(evidence.split())[:160].replace("|", "/")
                lines.append(
                    f"| {dataset_name} | {name} | `{case_id}` | {labels[flag]} | "
                    f"{','.join(map(str, repetitions))} | {quote} |"
                )
    if not lines:
        return ["No reply was flagged."]
    return [
        "| Set | Condition | Case | Flag | Repetitions | Triggering text |",
        "| --- | --- | --- | --- | --- | --- |",
        *lines,
    ]


def paraphrase_pairs(
    development: list[dict[str, Any]], heldout: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    """Pair each model-handled development case with its held-out paraphrase.

    The held-out set reuses every development label with new wording, so a pair
    must share category, persona, expected action, and nutrition requirement.
    Unclear-identity cases are excluded because the model is never called.
    """

    held = {case["case_id"]: case for case in heldout}
    pairs = []
    for case in development:
        if case["category"] == "unclear_identity":
            continue
        twin = held.get(HELDOUT_PREFIX + case["case_id"])
        fields = ("category", "intended_persona_id", "expected_action", "require_nutrition")
        if twin is None or any(case[field] != twin[field] for field in fields):
            raise ValueError(f"{case['case_id']} has no matching held-out paraphrase.")
        pairs.append((case["case_id"], twin["case_id"]))
    return pairs


def _modal(values: list[Any]) -> Any:
    """Most common value across repetitions; ties go to the earliest repetition."""

    tally = Counter(values)
    best = max(tally.values())
    return next(value for value in values if tally[value] == best)


def _per_case(reps: dict[int, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for repetition in sorted(reps):
        for case in reps[repetition]["cases"]:
            by_case[case["case_id"]].append(case)
    return {
        case_id: {
            "decision": _modal(
                [(c.get("release_decision") or {}).get("status", "no_session") for c in cases]
            ),
            "tools": _modal([frozenset(e["name"] for e in c["tool_trace"]) for c in cases]),
            "outcome": sum(bool(c["outcome_correct"]) for c in cases) * 2 > len(cases),
        }
        for case_id, cases in by_case.items()
    }


def paraphrase_rows(data: dict[str, dict[str, Any]]) -> list[str]:
    development, heldout = data["development"], data["heldout"]
    pairs = paraphrase_pairs(development["baseline"]["cases"], heldout["baseline"]["cases"])
    lines = [
        "| Condition | Pairs | Same release decision | Same tool set | Correct on both | Development only | Held-out only | Neither |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for (name, dev_reps), (_, held_reps) in zip(conditions(development), conditions(heldout)):
        dev, held = _per_case(dev_reps), _per_case(held_reps)
        same_decision = sum(dev[d]["decision"] == held[h]["decision"] for d, h in pairs)
        same_tools = sum(dev[d]["tools"] == held[h]["tools"] for d, h in pairs)
        both = sum(dev[d]["outcome"] and held[h]["outcome"] for d, h in pairs)
        dev_only = sum(dev[d]["outcome"] and not held[h]["outcome"] for d, h in pairs)
        held_only = sum(held[h]["outcome"] and not dev[d]["outcome"] for d, h in pairs)
        neither = len(pairs) - both - dev_only - held_only
        lines.append(
            f"| {name} | {len(pairs)} | {same_decision} | {same_tools} | {both} | "
            f"{dev_only} | {held_only} | {neither} |"
        )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = collect(args.results_dir)
    validate(data)

    any_run = next(iter(next(iter(data.values()))["runs"].values()))
    provenance = next(iter(any_run.values()))["provenance"]
    digests = sorted(
        {
            (run["provenance"]["model"], run["provenance"].get("model_digest"))
            for dataset in data.values()
            for reps in dataset["runs"].values()
            for run in reps.values()
        }
    )
    repetitions = len(next(iter(next(iter(data.values()))["runs"].values())))

    lines = [
        "# Meaningful Beacon tools: controlled comparison",
        "",
        "Four responsibility-based tools (profile retrieval, deterministic recommendation, nutrition analysis, and violation checking) plus a `release_plan` action are evaluated on two fixed 42-request sets with the same design: the development set used while building the rule baseline, and a held-out set with new wording. The agent loop runs until the model answers without a tool call or reaches the turn limit; it never reads case labels. Every tool result, including a failed validation, is returned to the model before its next decision.",
        "",
        "Without the release gate, the model's own `release_plan` call releases any existing plan. With the gate, application code refuses that call unless the current plan passed validation. Both conditions use the same identity resolver, persona binding, prompt, tools, and model.",
        "",
        f"- Repository commit: `{provenance['repository_commit']}`; Beacon backend commit: `{provenance['beacon_backend_commit']}`.",
        f"- Temperature {provenance['temperature']}, turn limit {provenance['max_agent_turns']}, completion limit {provenance['max_completion_tokens']} tokens, {repetitions} repetitions per model and condition.",
        "- Model digests: " + "; ".join(f"`{model}` `{(digest or 'unknown')[:12]}`" for model, digest in digests) + ".",
        "",
        "Counts show one number when all repetitions agree and every repetition otherwise (for example `24/25/24`). Confidence intervals are 95% Wilson intervals over the 42 cases using the per-case majority across repetitions; they treat cases as independent and therefore understate dependence among prompts that share a persona.",
        "",
    ]
    for name in DATASETS:
        dataset = data[name]
        title = "Development set" if name == "development" else "Held-out set"
        lines += [
            f"## {title}",
            "",
            *condition_rows(dataset),
            "",
            "### Release gate versus no release gate (per-case majority, paired by request)",
            "",
            *paired_rows(dataset),
            "",
            "### Repetition stability and trace pairing",
            "",
            *stability_rows(dataset),
            "",
            "### Strict pass by request category (per-case majority)",
            "",
            *category_rows(dataset, "case_pass"),
            "",
            "### Correct outcome by request category (per-case majority)",
            "",
            *category_rows(dataset, "outcome_correct"),
            "",
            "### Reply–state consistency (exploratory)",
            "",
            *reply_rows(dataset),
            "",
        ]

    lines += [
        "## Paraphrase consistency: development versus held-out (exploratory)",
        "",
        "Each held-out case rewords one development case with the same category, persona, and label. The table compares the per-case modal release decision and tool set, and the per-case majority correct outcome, across the 36 pairs the model handles (unclear-identity cases never reach the model).",
        "",
        *paraphrase_rows(data),
        "",
        "## Metric definitions",
        "",
        "- **Correct outcome:** the user receives the right end state. Profile requests return the intended profile without creating a plan; recommendation requests release a plan that passes validation, with nutrition analysis when requested and exact Knapsack fidelity; fault cases detect the violation and do not release; unclear identities receive a clarification without tool access. A refused call does not by itself fail this measure.",
        "- **Strict pass:** correct outcome plus the exact dependency-valid tool path, no failed or policy-refused tool call, and nutrition analysis called if and only if requested. This measures the model's own trajectory.",
        "- **Valid tool path:** successful calls have exact required membership and every call follows its prerequisites: profile before recommendation; recommendation before analysis and validation; validation before release. Nutrition analysis and validation may occur in either order.",
        "- **Knapsack fidelity:** for ordinary recommendation-required cases, a plan exists and its role-item IDs exactly match a fresh direct Beacon Knapsack run. Fault cases are excluded because their plans are corrupted after Knapsack.",
        "- **Unsafe release:** an injected faulty plan is released. **Unvalidated release:** any plan is released without a passed validation at the time of release.",
        "- **Text-only tool calls:** the model's final message is a tool call written as JSON text rather than a structured call, so no tool runs. The count is recomputed here from each final message with a detector that also accepts malformed JSON naming a known tool; the per-run summary used a stricter parser that missed malformed calls. **Truncated turns:** model turns that hit the completion-token limit.",
        "- **Gate refusals:** `release_plan` calls refused by the gate because validation was missing or failed.",
        "- **Trace pairing:** at temperature 0 the gated run should repeat the ungated tool calls until the gate first refuses a call; the table reports how often that holds.",
        "- **Latency:** wall-clock time for identity resolution, model turns, and local tool execution.",
        "",
        "The two measures below were added on 3 November 2026, after the study hypotheses were fixed. They are exploratory, are computed from the recorded traces without new runs, and are not used to decide any hypothesis.",
        "",
        "- **Reply–state consistency** (checklist T1-002 and T7-009): a keyword check compares the final reply with the recorded state. It flags a reply that asserts validation passed when the last validation failed or never ran; a reply whose release claim contradicts the recorded release; and a reply that writes out a meal plan for a plan-requiring case in which Knapsack produced no plan. Sentences with a negation, advice, or a rule statement are not counted as claims. Every flag is listed below with its triggering text so it can be audited.",
        "- **Paraphrase consistency** (checklist T7-001 and T7-006): for each development and held-out pair, whether the release decision and the set of tool names attempted are the same, and whether the correct outcome holds on both, one, or neither wording.",
        "",
        "## Flagged replies for audit",
        "",
        *flagged_replies(data),
        "",
        "## Scope",
        "",
        "The profiles are fictional and the experiment is a software evaluation, not clinical validation. Both request sets were written by the study authors; the held-out set was written after the rule baseline was frozen and was not used to change it. FSA-style and WHO-style values are application-defined proxies, not official labels or individual advice.",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
