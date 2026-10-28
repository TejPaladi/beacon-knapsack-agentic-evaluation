"""Compare Beacon Knapsack with direct LLM meal selection.

The LLM receives one persona and the full compact Beacon catalog. It selects
item IDs directly and cannot call Knapsack or any other recommendation tool.
Deterministic code is used only after generation to validate and score the
saved plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from beacon_m6 import (
        EVALUATION_DATE,
        _recommendation_helpers,
        beacon_backend_path,
        evaluate_knapsack_plan,
        load_personas,
        public_persona,
        run_knapsack_for_persona,
    )
except ModuleNotFoundError:
    from code.beacon_m6 import (
        EVALUATION_DATE,
        _recommendation_helpers,
        beacon_backend_path,
        evaluate_knapsack_plan,
        load_personas,
        public_persona,
        run_knapsack_for_persona,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://localhost:11434/v1"
ROLE_SYMBOLS = {
    "Main Course": "M",
    "Side": "S",
    "Dessert": "D",
    "Beverage": "B",
}
ROLE_KEYS = {
    "mainCourse": "main_course",
    "side": "side",
    "dessert": "dessert",
    "beverage": "beverage",
}
ROLE_TAGS = {
    "main_course": "Main Course",
    "side": "Side",
    "dessert": "Dessert",
    "beverage": "Beverage",
}

SYSTEM_PROMPT = """You are the meal selector in a controlled experiment.
Select every requested meal-role item directly from the supplied catalog.
No optimizer or tool will choose for you. Respect every true dietary condition.
Use preference sliders as soft preferences: 1=prefer, 0=neutral, -1=avoid.
Prefer variety and nutrition-goal fit. Return JSON only, with exactly this shape:
{"meals":[{"meal_name":"Breakfast","items":[{"role":"main_course","item_id":"1"}]}]}
Use only supplied IDs and requested roles. Do not include explanations."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_revision(path: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() or None


def _number(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("measure", 0)
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _nutrients(item: dict[str, Any]) -> tuple[float, float, float, float]:
    macro = item.get("macronutrients") or {}

    def find(*names: str) -> float:
        lowered = {str(key).lower(): value for key, value in macro.items()}
        for name in names:
            if name.lower() in lowered:
                return _number(lowered[name.lower()])
        return 0.0

    return (
        find("calories", "calorie"),
        find("carbohydrates", "carbs", "carbohydrate"),
        find("protein"),
        find("fiber", "fibre"),
    )


def catalog_records() -> list[dict[str, Any]]:
    """Return the full catalog in a compact model-facing representation."""

    helpers = _recommendation_helpers()
    records: list[dict[str, Any]] = []
    for item_id, item in helpers.food_items.items():
        roles = sorted(
            ROLE_SYMBOLS[role]
            for role in item.get("food_role", [])
            if role in {"Main Course", "Side", "Dessert"}
        )
        if not roles:
            continue
        kcal, carbs, protein, fiber = _nutrients(item)
        records.append(
            {
                "kind": "food",
                "id": str(item_id),
                "roles": "".join(roles),
                "name": str(item.get("recipe_name") or item_id),
                "dairy": int(bool(item.get("hasDairy", False))),
                "meat": int(bool(item.get("hasMeat", False))),
                "nuts": int(bool(item.get("hasNuts", False))),
                "low_sugar": int(bool(helpers._is_low_sugar(item))),
                "gluten_free": int(bool(helpers._is_gluten_free(item))),
                "vegan": int(bool(helpers._is_vegan(item))),
                "kcal": kcal,
                "carbs": carbs,
                "protein": protein,
                "fiber": fiber,
            }
        )
    for item_id, item in helpers.beverages.items():
        kcal, carbs, protein, fiber = _nutrients(item)
        records.append(
            {
                "kind": "beverage",
                "id": str(item_id),
                "roles": "B",
                "name": str(item.get("name") or item_id),
                "dairy": int(bool(item.get("hasDairy", False))),
                "meat": int(bool(item.get("hasMeat", False))),
                "nuts": int(bool(item.get("hasNuts", False))),
                "low_sugar": "-",
                "gluten_free": "-",
                "vegan": int(not bool(item.get("hasDairy", False))),
                "kcal": kcal,
                "carbs": carbs,
                "protein": protein,
                "fiber": fiber,
            }
        )
    return sorted(
        records,
        key=lambda record: (
            record["kind"],
            not record["id"].isdigit(),
            int(record["id"]) if record["id"].isdigit() else record["id"],
        ),
    )


def compact_catalog_text(records: list[dict[str, Any]]) -> str:
    header = "kind|id|roles|name|D|M|N|LS|GF|V|kcal|carbs|protein|fiber"
    rows = [header]
    for item in records:
        rows.append(
            "|".join(
                str(item[key])
                for key in (
                    "kind",
                    "id",
                    "roles",
                    "name",
                    "dairy",
                    "meat",
                    "nuts",
                    "low_sugar",
                    "gluten_free",
                    "vegan",
                    "kcal",
                    "carbs",
                    "protein",
                    "fiber",
                )
            )
        )
    return "\n".join(rows)


def prompt_for(persona_id: str, catalog_text: str) -> str:
    profile = public_persona(persona_id)
    return (
        "Create the requested one-day plan for this profile.\n"
        f"PROFILE={json.dumps(profile, separators=(',', ':'))}\n"
        "Catalog flags: D=dairy, M=meat, N=nuts, LS=low-sugar, "
        "GF=gluten-free, V=vegan; 1=true, 0=false, -=not applied.\n"
        f"CATALOG\n{catalog_text}"
    )


def call_model(base_url: str, model: str, prompt: str) -> tuple[str, dict[str, int]]:
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "max_tokens": 700,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model HTTP {error.code}: {detail[:500]}") from error
    message = body["choices"][0]["message"].get("content") or ""
    usage = body.get("usage") or {}
    return message, {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
    }


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("The model did not return a JSON object.")
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("The model response is not a JSON object.")
    return parsed


def _requested_meals(persona_id: str) -> dict[str, set[str]]:
    profile = public_persona(persona_id)
    return {
        meal["meal_name"]: {ROLE_KEYS[role] for role in meal["roles"]}
        for meal in profile["meal_roles"]
    }


def _catalog_indexes(
    records: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    foods = {record["id"]: record for record in records if record["kind"] == "food"}
    beverages = {
        record["id"]: record for record in records if record["kind"] == "beverage"
    }
    return foods, beverages


def score_selection(
    persona_id: str,
    response: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate an LLM plan and evaluate it only after selection is complete."""

    requested = _requested_meals(persona_id)
    foods, beverages = _catalog_indexes(records)
    persona = public_persona(persona_id)
    conditions = persona["dietary_conditions"]
    errors: list[str] = []
    hard_violations: list[str] = []
    meals_out: list[dict[str, Any]] = []
    observed: dict[str, dict[str, str]] = {}

    raw_meals = response.get("meals")
    if not isinstance(raw_meals, list):
        raw_meals = []
        errors.append("Missing meals list.")

    for raw_meal in raw_meals:
        if not isinstance(raw_meal, dict):
            errors.append("A meal is not an object.")
            continue
        meal_name = str(raw_meal.get("meal_name") or "")
        if meal_name not in requested:
            errors.append(f"Unexpected meal name: {meal_name!r}.")
            continue
        if meal_name in observed:
            errors.append(f"Duplicate meal: {meal_name}.")
            continue
        observed[meal_name] = {}
        items_out: list[dict[str, str]] = []
        raw_items = raw_meal.get("items")
        if not isinstance(raw_items, list):
            errors.append(f"{meal_name} is missing its items list.")
            continue
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                errors.append(f"{meal_name} contains a non-object item.")
                continue
            role = str(raw_item.get("role") or "")
            item_id = str(raw_item.get("item_id") or "")
            if role not in requested[meal_name]:
                errors.append(f"Unexpected or duplicate role {meal_name}/{role}.")
                continue
            if role in observed[meal_name]:
                errors.append(f"Duplicate role {meal_name}/{role}.")
                continue
            catalog = beverages if role == "beverage" else foods
            item = catalog.get(item_id)
            if item is None:
                errors.append(f"Unknown catalog ID {meal_name}/{role}/{item_id}.")
                continue
            expected_symbol = ROLE_SYMBOLS[ROLE_TAGS[role]]
            if expected_symbol not in item["roles"]:
                errors.append(f"Role mismatch {meal_name}/{role}/{item_id}.")
                continue
            if conditions["diabetes"] and item["low_sugar"] != 1 and role != "beverage":
                hard_violations.append(f"{meal_name}/{role}/{item_id}: not low-sugar")
            if conditions["gluten_free"] and item["gluten_free"] != 1 and role != "beverage":
                hard_violations.append(f"{meal_name}/{role}/{item_id}: not gluten-free")
            if conditions["vegan"] and item["vegan"] != 1:
                hard_violations.append(f"{meal_name}/{role}/{item_id}: not vegan")
            if conditions["vegetarian"] and item["meat"] == 1:
                hard_violations.append(f"{meal_name}/{role}/{item_id}: contains meat")
            observed[meal_name][role] = item_id
            items_out.append(
                {"role": role, "item_id": item_id, "name": str(item["name"])}
            )
        meals_out.append({"meal_name": meal_name, "items": items_out})

    role_coverage = all(
        meal_name in observed and set(observed[meal_name]) == roles
        for meal_name, roles in requested.items()
    ) and len(observed) == len(requested)
    selected_foods = [
        item_id
        for role_map in observed.values()
        for role, item_id in role_map.items()
        if role != "beverage"
    ]
    duplicate_food_count = len(selected_foods) - len(set(selected_foods))
    structurally_valid = role_coverage and not errors
    plan = {
        "persona_id": persona_id,
        "persona_name": persona["name"],
        "algorithm": "LLM-only direct selection",
        "catalog_scope": "all local Beacon catalog sources",
        "date": EVALUATION_DATE.strftime("%Y-%m-%d"),
        "meals": meals_out,
    }
    quality = None
    if structurally_valid:
        quality = evaluate_knapsack_plan(persona_id, plan)

    reference = run_knapsack_for_persona(persona_id)
    reference_map = {
        meal["meal_name"]: {
            item["role"]: str(item["item_id"]) for item in meal["items"]
        }
        for meal in reference["meals"]
    }
    return {
        "plan": plan,
        "format_and_catalog_valid": structurally_valid,
        "requested_role_coverage": role_coverage,
        "hard_constraint_adherence": structurally_valid and not hard_violations,
        "hard_constraint_violations": hard_violations,
        "validation_errors": errors,
        "duplicate_food_count": duplicate_food_count,
        "exact_knapsack_match": structurally_valid and observed == reference_map,
        "quality_evaluation": quality,
        "case_pass": structurally_valid and not hard_violations,
    }


def run_case(
    persona_id: str,
    model: str,
    base_url: str,
    records: list[dict[str, Any]],
    catalog_text: str,
) -> dict[str, Any]:
    prompt = prompt_for(persona_id, catalog_text)
    started = time.perf_counter()
    raw_response = ""
    api_error = None
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    parsed: dict[str, Any] | None = None
    try:
        raw_response, usage = call_model(base_url, model, prompt)
        parsed = parse_json_object(raw_response)
    except Exception as error:
        api_error = str(error)
    latency_ms = (time.perf_counter() - started) * 1000
    scored = (
        score_selection(persona_id, parsed, records)
        if parsed is not None
        else {
            "plan": None,
            "format_and_catalog_valid": False,
            "requested_role_coverage": False,
            "hard_constraint_adherence": False,
            "hard_constraint_violations": [],
            "validation_errors": [api_error or "No parsed response."],
            "duplicate_food_count": 0,
            "exact_knapsack_match": False,
            "quality_evaluation": None,
            "case_pass": False,
        }
    )
    return {
        "persona_id": persona_id,
        "persona_name": public_persona(persona_id)["name"],
        "model": model,
        "raw_response": raw_response,
        "api_error": api_error,
        "latency_ms": latency_ms,
        "usage": usage,
        **scored,
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [case for case in cases if case["quality_evaluation"] is not None]

    def metric(path: tuple[str, ...]) -> float | None:
        values: list[float] = []
        for case in completed:
            value: Any = case
            for key in path:
                value = value[key]
            values.append(float(value))
        return _mean(values)

    return {
        "cases": len(cases),
        "safe_valid_plans": sum(case["case_pass"] for case in cases),
        "format_and_catalog_valid": sum(
            case["format_and_catalog_valid"] for case in cases
        ),
        "hard_constraint_adherent": sum(
            case["hard_constraint_adherence"] for case in cases
        ),
        "hard_constraint_violations": sum(
            len(case["hard_constraint_violations"]) for case in cases
        ),
        "exact_knapsack_matches": sum(case["exact_knapsack_match"] for case in cases),
        "mean_duplicate_food_count": _mean(
            [float(case["duplicate_food_count"]) for case in cases]
        ),
        "mean_legacy_goodness": metric(("quality_evaluation", "legacy_goodness", "score")),
        "mean_beacon_quality": metric(("quality_evaluation", "quality", "quality_score")),
        "mean_nutrition_fit": metric(
            ("quality_evaluation", "nutrition_goal_adherence", "mean_fit")
        ),
        "mean_latency_ms": _mean([float(case["latency_ms"]) for case in cases]),
        "total_prompt_tokens": sum(case["usage"]["prompt_tokens"] for case in cases),
        "total_completion_tokens": sum(
            case["usage"]["completion_tokens"] for case in cases
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    records = catalog_records()
    catalog_text = compact_catalog_text(records)
    persona_ids = list(load_personas())
    if args.limit is not None:
        persona_ids = persona_ids[: args.limit]
    cases = []
    for index, persona_id in enumerate(persona_ids, 1):
        print(f"[{index}/{len(persona_ids)}] {args.model}: {persona_id}", flush=True)
        cases.append(run_case(persona_id, args.model, args.base_url, records, catalog_text))

    direct_cases = []
    for persona_id in persona_ids:
        started = time.perf_counter()
        plan = run_knapsack_for_persona(persona_id)
        latency_ms = (time.perf_counter() - started) * 1000
        direct_cases.append(
            {
                "persona_id": persona_id,
                "plan": plan,
                "latency_ms": latency_ms,
                "quality_evaluation": evaluate_knapsack_plan(persona_id, plan),
            }
        )

    result = {
        "experiment": "Beacon Knapsack versus LLM-only meal selection",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "model": args.model,
            "provider": "Ollama OpenAI-compatible API",
            "base_url": args.base_url,
            "temperature": 0,
            "repository_commit": git_revision(PROJECT_ROOT),
            "beacon_backend_commit": git_revision(beacon_backend_path()),
            "system_prompt_sha256": sha256_bytes(SYSTEM_PROMPT.encode()),
            "catalog_sha256": sha256_bytes(catalog_text.encode()),
            "catalog_records": len(records),
            "selector": "LLM direct JSON selection; no recommendation tool or pre-filter",
            "evaluator": "Post-hoc deterministic validation and Beacon quality metrics",
        },
        "summary": summarize(cases),
        "llm_only_cases": cases,
        "direct_knapsack_cases": direct_cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
