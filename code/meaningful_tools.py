"""Meaningful, independently testable tools for the Beacon agent study.

The tool boundaries follow responsibilities rather than implementation steps:
profile retrieval, deterministic recommendation, nutrition analysis, and safety
validation. The session retains the generated plan so the model never copies a
large plan back into later tool arguments.
"""

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from typing import Any

try:
    from beacon_m6 import (
        calculate_plan_health_scores,
        check_plan_violations,
        list_personas,
        public_persona,
        run_knapsack_for_persona,
    )
except ModuleNotFoundError:
    from code.beacon_m6 import (
        calculate_plan_health_scores,
        check_plan_violations,
        list_personas,
        public_persona,
        run_knapsack_for_persona,
    )


MEANINGFUL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_persona_profile",
            "description": (
                "Resolve one stored persona name or identifier and return that "
                "fictional profile. Use this for profile questions and before "
                "requesting a recommendation."
            ),
            "parameters": {
                "type": "object",
                "properties": {"persona_query": {"type": "string"}},
                "required": ["persona_query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_meal_plan",
            "description": (
                "Run the deterministic Beacon Knapsack recommender for the "
                "already-fetched persona. The model does not select food."
            ),
            "parameters": {
                "type": "object",
                "properties": {"persona_id": {"type": "string"}},
                "required": ["persona_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_nutrition_scores",
            "description": (
                "Analyze the current recommended plan. Return nutrient totals, "
                "goal fit, and FSA/WHO-style proxy scores with missing-data coverage. "
                "Call only when the user requests nutrition or health-score details."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_plan_violations",
            "description": (
                "Validate the current recommended plan for missing roles, invalid "
                "items, duplicate foods, and stored dietary-condition violations. "
                "Every recommendation must be checked before it can be released."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).casefold()
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def resolve_profile_query(query: str) -> dict[str, str]:
    """Resolve one exact ID, full name, or unique first name."""

    normalized = _normalize(query)
    entries = [
        {
            "persona_id": str(item["persona_id"]),
            "name": str(item["name"]),
            "id_normalized": _normalize(str(item["persona_id"])),
            "full": _normalize(str(item["name"])),
            "first": _normalize(str(item["name"]).split()[0]),
        }
        for item in list_personas()
    ]
    exact = [
        entry
        for entry in entries
        if normalized in {entry["id_normalized"], entry["full"], entry["first"]}
    ]
    if len(exact) != 1:
        raise ValueError("Persona query must resolve to exactly one stored profile.")
    return {"persona_id": exact[0]["persona_id"], "name": exact[0]["name"]}


class MeaningfulToolSession:
    """Stateful tool gateway with dependency and optional identity enforcement."""

    def __init__(
        self,
        *,
        allowed_persona_id: str | None = None,
        fault_injection: str | None = None,
    ) -> None:
        self.allowed_persona_id = allowed_persona_id
        self.fault_injection = fault_injection
        self.trace: list[dict[str, Any]] = []
        self.profile: dict[str, Any] | None = None
        self.plan: dict[str, Any] | None = None
        self.nutrition: dict[str, Any] | None = None
        self.violation_check: dict[str, Any] | None = None
        self.policy_blocks = 0

    def _record(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        ok: bool,
        error: str | None = None,
    ) -> None:
        event: dict[str, Any] = {"name": name, "arguments": arguments, "ok": ok}
        if error is not None:
            event["error"] = error
        self.trace.append(event)

    def _compact_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "persona_id": plan["persona_id"],
            "persona_name": plan["persona_name"],
            "algorithm": plan["algorithm"],
            "meals": plan["meals"],
        }

    def _apply_fault(self, plan: dict[str, Any]) -> dict[str, Any]:
        if self.fault_injection is None:
            return plan
        mutated = deepcopy(plan)
        if self.fault_injection == "remove_first_role":
            mutated["meals"][0]["items"] = mutated["meals"][0]["items"][1:]
            mutated["normalized_meals"] = tuple(
                (
                    meal["meal_name"],
                    tuple(
                        sorted(
                            (str(item["role"]), str(item["item_id"]))
                            for item in meal.get("items", [])
                        )
                    ),
                )
                for meal in mutated["meals"]
            )
            return mutated
        raise ValueError(f"Unknown fault injection: {self.fault_injection}")

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "fetch_persona_profile":
                resolved = resolve_profile_query(str(arguments["persona_query"]))
                persona_id = resolved["persona_id"]
                if (
                    self.allowed_persona_id is not None
                    and persona_id != self.allowed_persona_id
                ):
                    self.policy_blocks += 1
                    raise ValueError("Profile does not match the application-resolved persona.")
                self.profile = public_persona(persona_id)
                result: dict[str, Any] = self.profile
            elif name == "recommend_meal_plan":
                persona_id = str(arguments["persona_id"])
                if self.profile is None or self.profile["persona_id"] != persona_id:
                    raise ValueError("Fetch this persona profile before recommendation.")
                self.plan = self._apply_fault(run_knapsack_for_persona(persona_id))
                self.nutrition = None
                self.violation_check = None
                result = self._compact_plan(self.plan)
            elif name == "calculate_nutrition_scores":
                if self.plan is None or self.profile is None:
                    raise ValueError("Create a recommendation before nutrition analysis.")
                self.nutrition = calculate_plan_health_scores(
                    str(self.profile["persona_id"]), self.plan
                )
                result = {
                    "persona_id": self.nutrition["persona_id"],
                    "nutrient_totals": self.nutrition["nutrient_totals"],
                    "goal_fit": self.nutrition["goal_fit"],
                    "fsa_style_proxy": self.nutrition["fsa_style_proxy"],
                    "who_style_proxy": self.nutrition["who_style_proxy"],
                    "scope_note": self.nutrition["scope_note"],
                }
            elif name == "check_plan_violations":
                if self.plan is None or self.profile is None:
                    raise ValueError("Create a recommendation before validation.")
                self.violation_check = check_plan_violations(
                    str(self.profile["persona_id"]), self.plan
                )
                result = self.violation_check
            else:
                raise ValueError(f"Unknown tool: {name}")
            self._record(name, arguments, ok=True)
            return result
        except Exception as error:
            self._record(name, arguments, ok=False, error=str(error))
            return {"error": str(error)}

    def release_decision(self, *, enforce_check: bool) -> dict[str, Any]:
        """Apply the application boundary after the model stops."""

        if self.plan is None:
            return {"status": "no_plan", "released": False, "reason": "No plan exists."}
        if not enforce_check:
            return {
                "status": "released_unchecked",
                "released": True,
                "reason": "Release gate disabled for the ablation.",
            }
        if self.violation_check is None:
            return {
                "status": "blocked_missing_check",
                "released": False,
                "reason": "Violation check was not completed.",
            }
        if not self.violation_check["passed"]:
            return {
                "status": "blocked_violations",
                "released": False,
                "reason": "Deterministic validation found a hard violation.",
            }
        return {"status": "released", "released": True, "reason": "Validation passed."}
