"""Experiment 7: constrained hybrid reranking.

Beacon Knapsack plans five consecutive days for each persona; identical days
are removed and every remaining candidate must pass validation. A selector then
picks one candidate for a stated preference: the Knapsack default (candidate
1), the frozen keyword reranker, or a local model restricted by structured
output to the candidate numbers. Scoring compares the choice with the
candidates that have the best total for the requested nutrient.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from beacon_m6 import (
        EVALUATION_DATE,
        _meal_configs,
        _recommendation_helpers,
        beacon_backend_path,
        check_plan_violations,
        load_personas,
        normalized_meals,
        run_knapsack_for_persona,
    )
    from benchmark import json_safe
    from meaningful_tools_benchmark import ollama_model_digest
    from recommendation_source_benchmark import catalog_records
    from robustness_benchmark import (
        DEFAULT_BASE_URL,
        MAX_COMPLETION_TOKENS,
        git_revision,
        git_worktree_dirty,
        sha256_bytes,
    )
    from rule_reranker import choose as choose_with_rules
except ModuleNotFoundError:
    from code.beacon_m6 import (
        EVALUATION_DATE,
        _meal_configs,
        _recommendation_helpers,
        beacon_backend_path,
        check_plan_violations,
        load_personas,
        normalized_meals,
        run_knapsack_for_persona,
    )
    from code.benchmark import json_safe
    from code.meaningful_tools_benchmark import ollama_model_digest
    from code.recommendation_source_benchmark import catalog_records
    from code.robustness_benchmark import (
        DEFAULT_BASE_URL,
        MAX_COMPLETION_TOKENS,
        git_revision,
        git_worktree_dirty,
        sha256_bytes,
    )
    from code.rule_reranker import choose as choose_with_rules


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "data" / "preference_requests.json"
RULE_RERANKER_PATH = PROJECT_ROOT / "code" / "rule_reranker.py"
SELECTORS = ("default", "rules", "model")
MODELS = ("granite4:3b", "llama3.2:3b", "qwen3.5:4b")
NUTRIENTS = {"kcal": "kcal", "carbs": "g carbohydrates", "protein": "g protein", "fiber": "g fiber"}
PLAN_DAYS = 5
TEMPERATURE = 0

SYSTEM_PROMPT = """You choose one meal plan for a person. Every candidate plan already satisfies the person's stored dietary restrictions.
Pick the candidate that best matches the person's stated preference, using the listed items and nutrient totals.
Answer with the candidate number only."""


@lru_cache(maxsize=None)
def build_candidates(persona_id: str) -> tuple[dict[str, Any], ...]:
    """Distinct, validated Knapsack day-plans; candidate 1 is the one-day default."""

    persona = load_personas()[persona_id]
    preferences = persona["dietaryPreferences"]
    helpers = _recommendation_helpers()
    plan = helpers.gen_knapsack_rec(
        num_days=PLAN_DAYS,
        meal_configs=_meal_configs(persona),
        starting_date=EVALUATION_DATE,
        dietary_conditions={
            "diabetes": preferences["diabetes"],
            "gluten_free": preferences["glutenFree"],
            "vegan": preferences["vegan"],
            "vegetarian": preferences["vegetarian"],
        },
        meal_plan_name=f"{persona['name']} reranking candidates",
        algorithm="m6",
        user_preferences={
            "dairyPreference": preferences["dairy"],
            "meatPreference": preferences["meat"],
            "nutsPreference": preferences["nuts"],
        },
    )
    records = {(r["kind"], r["id"]): r for r in catalog_records()}
    candidates: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for date, day in plan.items():
        signature = normalized_meals({date: day})
        if signature in seen:
            continue
        seen.add(signature)
        meals, totals = [], {key: 0.0 for key in NUTRIENTS}
        for meal in day["meals"]:
            items = []
            for role, item_id in meal["meal_types"].items():
                record = records[("beverage" if role == "beverage" else "food", str(item_id))]
                items.append({"role": role, "item_id": str(item_id), "name": record["name"]})
                for key in NUTRIENTS:
                    totals[key] += float(record[key] or 0)
            meals.append({"meal_name": meal["meal_name"], "items": items})
        candidate_plan = {"persona_id": persona_id, "date": date, "meals": meals}
        candidates.append(
            {
                "number": len(candidates) + 1,
                "date": date,
                "meals": meals,
                "totals": {key: round(value, 1) for key, value in totals.items()},
                "passes_validation": check_plan_violations(persona_id, candidate_plan)["passed"],
                "signature": signature,
            }
        )
    if candidates[0]["signature"] != run_knapsack_for_persona(persona_id)["normalized_meals"]:
        raise ValueError(f"Candidate 1 for {persona_id} is not the one-day Knapsack plan.")
    if not all(c["passes_validation"] for c in candidates):
        raise ValueError(f"A candidate for {persona_id} fails validation.")
    return tuple(candidates)


def candidates_text(candidates: tuple[dict[str, Any], ...]) -> str:
    blocks = []
    for candidate in candidates:
        meals = "; ".join(
            f"{meal['meal_name']}: " + ", ".join(item["name"] for item in meal["items"])
            for meal in candidate["meals"]
        )
        totals = ", ".join(f"{candidate['totals'][k]:,.0f} {unit}" for k, unit in NUTRIENTS.items())
        blocks.append(f"Candidate {candidate['number']}: {meals}. Totals: {totals}.")
    return "\n".join(blocks)


def best_numbers(case: dict[str, Any], candidates: tuple[dict[str, Any], ...]) -> list[int]:
    values = {c["number"]: case["direction"] * c["totals"][case["nutrient"]] for c in candidates}
    best = max(values.values())
    return [number for number, value in values.items() if value == best]


def load_cases(path: Path = DEFAULT_DATASET) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if len(cases) != 48 or len({c["case_id"] for c in cases}) != 48:
        raise ValueError("Expected 48 uniquely identified preference requests.")
    for case in cases:
        if case["nutrient"] not in NUTRIENTS or case["direction"] not in (1, -1):
            raise ValueError(f"Invalid preference in {case['case_id']}.")
        if case["wording"] not in ("explicit", "implicit"):
            raise ValueError(f"Invalid wording in {case['case_id']}.")
    return cases


def call_model(base_url: str, model: str, case: dict[str, Any], candidates: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    root = base_url.rstrip("/").removesuffix("/v1")
    name = load_personas()[case["persona_id"]]["name"]
    schema = {
        "type": "object",
        "properties": {"candidate": {"type": "integer", "enum": [c["number"] for c in candidates]}},
        "required": ["candidate"],
        "additionalProperties": False,
    }
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"{name} says: \"{case['request']}\"\n\nCandidate plans:\n{candidates_text(candidates)}",
                },
            ],
            "format": schema,
            "stream": False,
            "think": False,
            "options": {"temperature": TEMPERATURE, "num_predict": MAX_COMPLETION_TOKENS},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{root}/api/chat", data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model HTTP {error.code}: {detail[:500]}") from error
    content = body["message"].get("content") or ""
    try:
        chosen = int(json.loads(content)["candidate"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        chosen = None
    return {"raw_answer": content, "chosen": chosen, "done_reason": body.get("done_reason")}


def run_case(case: dict[str, Any], selector: str, model: str | None, base_url: str) -> dict[str, Any]:
    started = time.perf_counter()
    candidates = build_candidates(case["persona_id"])
    record: dict[str, Any] = {key: case[key] for key in ("case_id", "persona_id", "nutrient", "direction", "wording", "request")}
    if selector == "default":
        chosen = 1
    elif selector == "rules":
        chosen = choose_with_rules(case["request"], list(candidates))
    else:
        response = call_model(base_url, str(model), case, candidates)
        record.update({k: response[k] for k in ("raw_answer", "done_reason")})
        chosen = response["chosen"]
    best = best_numbers(case, candidates)
    chosen_candidate = next((c for c in candidates if c["number"] == chosen), None)
    record.update(
        {
            "candidate_count": len(candidates),
            "best_candidates": best,
            "default_is_best": 1 in best,
            "chosen": chosen,
            "invalid_answer": chosen_candidate is None,
            "satisfied": chosen in best,
            "chosen_passes_validation": bool(chosen_candidate and chosen_candidate["passes_validation"]),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    )
    return record


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    def satisfied(subset: list[dict[str, Any]]) -> int:
        return sum(c["satisfied"] for c in subset)

    explicit = [c for c in cases if c["wording"] == "explicit"]
    implicit = [c for c in cases if c["wording"] == "implicit"]
    open_cases = [c for c in cases if not c["default_is_best"]]
    return {
        "cases": len(cases),
        "satisfied": satisfied(cases),
        "explicit_satisfied": satisfied(explicit),
        "implicit_satisfied": satisfied(implicit),
        "non_default_cases": len(open_cases),
        "non_default_satisfied": satisfied(open_cases),
        "hard_violations": sum(not c["chosen_passes_validation"] for c in cases),
        "invalid_answers": sum(c["invalid_answer"] for c in cases),
        "mean_latency_ms": round(sum(c["latency_ms"] for c in cases) / len(cases), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selector", choices=SELECTORS, required=True)
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--repetition", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.selector == "model") != bool(args.model):
        parser.error("--model is required for the model selector and only for it.")

    cases = load_cases()
    observed = []
    for index, case in enumerate(cases, start=1):
        observed.append(run_case(case, args.selector, args.model, args.base_url))
        print(f"[{index}/{len(cases)}] {case['case_id']}: chose {observed[-1]['chosen']}", flush=True)
    candidate_sets = {
        pid: [{k: c[k] for k in ("number", "date", "meals", "totals")} for c in build_candidates(pid)]
        for pid in sorted({c["persona_id"] for c in cases})
    }
    is_model = args.selector == "model"
    result = {
        "experiment": "constrained_hybrid_reranking",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "selector": args.selector,
            "model": args.model,
            "model_digest": ollama_model_digest(args.base_url, args.model) if is_model else None,
            "temperature": TEMPERATURE if is_model else None,
            "thinking": False if is_model else None,
            "repetition": args.repetition,
            "dataset": str(DEFAULT_DATASET.relative_to(PROJECT_ROOT)),
            "dataset_sha256": sha256_bytes(DEFAULT_DATASET.read_bytes()),
            "system_prompt_sha256": sha256_bytes(SYSTEM_PROMPT.encode("utf-8")),
            "rule_reranker_sha256": sha256_bytes(RULE_RERANKER_PATH.read_bytes()),
            "candidates_sha256": hashlib.sha256(
                json.dumps(candidate_sets, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "repository_commit": git_revision(PROJECT_ROOT),
            "worktree_dirty": git_worktree_dirty(PROJECT_ROOT),
            "beacon_backend_commit": git_revision(beacon_backend_path()),
        },
        "summary": summarize(observed),
        "candidates": candidate_sets,
        "cases": observed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
