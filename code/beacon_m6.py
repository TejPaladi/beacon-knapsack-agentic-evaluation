"""Thin experiment adapter around Beacon's existing Knapsack pipeline.

This module does not reimplement Knapsack.  It imports Beacon's
``gen_knapsack_rec(..., algorithm='m6')`` so both experimental conditions use
the same dietary filtering, preference tie-breaker, Knapsack selector, and
calendar diversity adapter as the application. ``m6`` is Beacon's internal
algorithm identifier; this experiment calls it Knapsack.
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
PERSONAS_PATH = EXPERIMENT_ROOT / "data" / "personas.json"
EVALUATION_DATE = datetime(2026, 1, 5)


class BeaconRuntimeError(RuntimeError):
    """Raised when the local Beacon backend cannot be loaded."""


def beacon_backend_path() -> Path:
    """Find Beacon's backend without copying recommendation code or its catalog.

    ``BEACON_BACKEND`` is the supported configuration.  The two sibling
    directories below are only convenient local defaults after cloning this
    evaluation repository beside a compatible Beacon checkout.
    """

    configured = os.environ.get("BEACON_BACKEND")
    candidates = [Path(configured)] if configured else []
    candidates.extend(
        [
            EXPERIMENT_ROOT.parent / "beacon-of-hope-2" / "backend",
            EXPERIMENT_ROOT.parent / "beacon-of-hope-2-main-2" / "backend",
        ]
    )
    for candidate in candidates:
        if (candidate / "manage.py").is_file():
            return candidate.resolve()
    raise BeaconRuntimeError(
        "Beacon backend was not found. Set BEACON_BACKEND to the directory "
        "containing Beacon's manage.py."
    )


@lru_cache(maxsize=1)
def _recommendation_helpers():
    """Initialize Beacon's Django runtime and return its actual helper module."""

    backend = beacon_backend_path()
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        import django

        django.setup()
        from core.modules import recommendation_helpers
    except ModuleNotFoundError as error:
        raise BeaconRuntimeError(
            "Run this experiment with Beacon's backend virtual environment. "
            "See README.md for the exact command."
        ) from error
    return recommendation_helpers


@lru_cache(maxsize=1)
def load_personas() -> dict[str, dict[str, Any]]:
    with PERSONAS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def public_persona(persona_id: str) -> dict[str, Any]:
    """Return only the persona fields relevant to Knapsack selection."""

    persona = load_personas().get(persona_id)
    if persona is None:
        raise ValueError(f"Unknown persona: {persona_id}")
    preferences = persona["dietaryPreferences"]
    return {
        "persona_id": persona_id,
        "name": persona["name"],
        "dietary_conditions": {
            "diabetes": preferences["diabetes"],
            "gluten_free": preferences["glutenFree"],
            "vegan": preferences["vegan"],
            "vegetarian": preferences["vegetarian"],
        },
        "preference_sliders": {
            "dairyPreference": preferences["dairy"],
            "meatPreference": preferences["meat"],
            "nutsPreference": preferences["nuts"],
        },
        "meal_roles": [
            {
                "meal_name": option["mealName"],
                "roles": [
                    role
                    for role, requested in option["mealTypes"].items()
                    if requested
                ],
            }
            for option in persona["mealSpecificOptions"]
        ],
        "nutritional_goals": persona["nutritionalGoals"],
    }


def list_personas() -> list[dict[str, str]]:
    """Return the agent's available persona identifiers and display names."""

    return [
        {"persona_id": persona_id, "name": persona["name"]}
        for persona_id, persona in load_personas().items()
    ]


def _meal_configs(persona: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "meal_name": option["mealName"],
            "meal_types": {
                "main_course": option["mealTypes"]["mainCourse"],
                "side": option["mealTypes"]["side"],
                "dessert": option["mealTypes"]["dessert"],
                "beverage": option["mealTypes"]["beverage"],
            },
        }
        for option in persona["mealSpecificOptions"]
    ]


def endpoint_request_payload(persona_id: str) -> dict[str, Any]:
    """Build the public Knapsack endpoint request for the fixed evaluation scope.

    ``user_id`` is intentionally ``None``. The endpoint accepts the key, skips
    persistence for a falsy ID, and therefore exercises recommendation code
    without creating or changing a Beacon user record. The experiment has no
    organization-specific source-access profile, so it evaluates the same
    all-sources catalog scope used by :func:`run_m6_for_persona`.
    """

    persona = load_personas().get(persona_id)
    if persona is None:
        raise ValueError(f"Unknown persona: {persona_id}")
    preferences = persona["dietaryPreferences"]
    return {
        "meal_plan_name": f"{persona['name']} Knapsack endpoint equivalence",
        "starting_date": EVALUATION_DATE.strftime("%Y-%m-%d"),
        "meal_plan_config": {
            "num_days": 1,
            "num_meals": persona["mealPlanConfig"]["mealsPerDay"],
            "meal_configs": _meal_configs(persona),
        },
        "user_preferences": {
            "dairyPreference": preferences["dairy"],
            "meatPreference": preferences["meat"],
            "nutsPreference": preferences["nuts"],
        },
        "dietary_conditions": {
            "diabetes": preferences["diabetes"],
            "gluten_free": preferences["glutenFree"],
            "vegan": preferences["vegan"],
            "vegetarian": preferences["vegetarian"],
        },
        "user_id": None,
    }


def _item_name(item_id: str, helpers: Any) -> str:
    item = helpers.food_items.get(str(item_id)) or helpers.beverages.get(str(item_id), {})
    return str(
        item.get("recipe_name")
        or item.get("beverage_name")
        or item.get("name")
        or item_id
    )


def normalized_meals(plan: dict[str, Any]) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """Remove generated database IDs and preserve only recommendation content."""

    day = next(iter(plan.values()))
    return tuple(
        (
            meal["meal_name"],
            tuple(sorted((role, str(item_id)) for role, item_id in meal["meal_types"].items())),
        )
        for meal in day["meals"]
    )


def normalized_endpoint_days(days: dict[str, Any]) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """Normalize the endpoint's ``days`` object to the experiment comparison form."""

    return normalized_meals(days)


def run_knapsack_for_persona(persona_id: str) -> dict[str, Any]:
    """Run Beacon's actual Knapsack pipeline for one stored persona.

    Beacon currently selects this implementation through the internal value
    ``algorithm='m6'``.  That implementation detail is not a separate
    recommender: the application labels it traditional Knapsack.
    """

    persona = load_personas().get(persona_id)
    if persona is None:
        raise ValueError(f"Unknown persona: {persona_id}")

    preferences = persona["dietaryPreferences"]
    helpers = _recommendation_helpers()
    plan = helpers.gen_knapsack_rec(
        num_days=1,
        meal_configs=_meal_configs(persona),
        starting_date=EVALUATION_DATE,
        dietary_conditions={
            "diabetes": preferences["diabetes"],
            "gluten_free": preferences["glutenFree"],
            "vegan": preferences["vegan"],
            "vegetarian": preferences["vegetarian"],
        },
        meal_plan_name=f"{persona['name']} Knapsack evaluation",
        algorithm="m6",
        user_preferences={
            "dairyPreference": preferences["dairy"],
            "meatPreference": preferences["meat"],
            "nutsPreference": preferences["nuts"],
        },
    )
    day = next(iter(plan.values()))
    return {
        "persona_id": persona_id,
        "persona_name": persona["name"],
        "algorithm": "Beacon Knapsack",
        "catalog_scope": "all local Beacon catalog sources",
        "date": next(iter(plan.keys())),
        "meals": [
            {
                "meal_name": meal["meal_name"],
                "items": [
                    {"role": role, "item_id": str(item_id), "name": _item_name(item_id, helpers)}
                    for role, item_id in meal["meal_types"].items()
                ],
            }
            for meal in day["meals"]
        ],
        "normalized_meals": normalized_meals(plan),
    }


def _plan_days(plan: dict[str, Any]) -> dict[str, Any]:
    """Restore the compact experiment plan to Beacon's evaluator input shape."""

    return {
        str(plan["date"]): {
            "meals": [
                {
                    "meal_name": meal["meal_name"],
                    "meal_types": {
                        item["role"]: str(item["item_id"])
                        for item in meal.get("items", [])
                    },
                }
                for meal in plan.get("meals", [])
            ]
        }
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def evaluate_knapsack_plan(persona_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Score an observed plan using Beacon's existing quality evaluators.

    ``legacy_goodness`` is the score shown first in Beacon's comparison UI:
    the equally weighted mean of meal variety, role coverage, and preference
    constraint scores. ``quality`` is Beacon's newer composite evaluator; its
    ``nutrition_fit`` component is the daily nutrition-goal adherence score.
    Neither evaluator changes a recommendation.
    """

    persona = load_personas().get(persona_id)
    if persona is None:
        raise ValueError(f"Unknown persona: {persona_id}")

    helpers = _recommendation_helpers()
    from core.modules.quality_evaluator import RecommendationQualityEvaluator

    preferences = persona["dietaryPreferences"]
    user_preferences = {
        "dairyPreference": preferences["dairy"],
        "meatPreference": preferences["meat"],
        "nutsPreference": preferences["nuts"],
    }
    dietary_conditions = {
        "diabetes": preferences["diabetes"],
        "gluten_free": preferences["glutenFree"],
        "vegan": preferences["vegan"],
        "vegetarian": preferences["vegetarian"],
    }
    meal_configs = _meal_configs(persona)
    days = _plan_days(plan)

    # This is Beacon's original goodness implementation. It mutates its
    # first argument, so score a copy and preserve the observed plan.
    original_scores = helpers.calculate_goodness(
        deepcopy(days), meal_configs, user_preferences
    )
    component_means = {
        "variety": _mean([float(value) for value in original_scores["variety_scores"]]),
        "role_coverage": _mean(
            [float(value) for value in original_scores["coverage_scores"]]
        ),
        "preference_constraint": _mean(
            [float(value) for value in original_scores["constraint_scores"]]
        ),
    }
    legacy_goodness = _mean(
        [value for value in component_means.values() if value is not None]
    )

    evaluator = RecommendationQualityEvaluator(
        food_items=helpers.food_items,
        beverages=helpers.beverages,
    )
    quality = evaluator.evaluate(
        meal_plan={"days": days},
        meal_configs=meal_configs,
        user_preferences=user_preferences,
        dietary_conditions=dietary_conditions,
        nutritional_goals=persona["nutritionalGoals"],
        num_days=1,
    )

    # Use the evaluator's own item lookup and nutrient extraction so the
    # displayed totals use precisely the data used by ``nutrition_fit``.
    assignments, _ = evaluator._collect_assignments(
        {"days": days}, meal_configs, num_days=1
    )
    totals = {"calories": 0.0, "carbs": 0.0, "protein": 0.0, "fiber": 0.0}
    for assignment in assignments:
        if not assignment["requested"] or assignment.get("item") is None:
            continue
        nutrients = evaluator._extract_nutrients(assignment["item"])
        for nutrient in totals:
            totals[nutrient] += float(nutrients.get(nutrient, 0.0))

    goals = {
        nutrient: float(persona["nutritionalGoals"][nutrient])
        for nutrient in totals
    }
    per_nutrient_fit = {
        nutrient: round(
            max(0.0, 1.0 - abs(totals[nutrient] - goals[nutrient]) / goals[nutrient]),
            6,
        )
        for nutrient in totals
    }

    return {
        "legacy_goodness": {
            "score": legacy_goodness,
            "components": component_means,
        },
        "quality": quality,
        "nutrition_goal_adherence": {
            "definition": "1 - absolute(actual - goal) / goal, clipped to [0, 1]",
            "goals": goals,
            "actual_totals": {key: round(value, 6) for key, value in totals.items()},
            "per_nutrient_fit": per_nutrient_fit,
            "mean_fit": quality["scores"]["nutrition_fit"],
        },
    }
