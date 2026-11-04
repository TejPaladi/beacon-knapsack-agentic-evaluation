"""Keyword reranker for Experiment 7 (constrained hybrid reranking).

This is the declared no-LLM baseline. It was written from a general
specification and committed before the Experiment 7 requests existed. It
detects one nutrient and a direction from keywords and common synonyms, then
picks the candidate with the best total for that nutrient. Without a cue it
keeps candidate 1, the plan Knapsack returns for a single day.
"""

from __future__ import annotations

import re
from typing import Any

# Words that point to a nutrient, each with the direction it implies when no
# explicit direction word is present (+1 more, -1 less).
NUTRIENT_CUES = {
    "protein": {
        "protein": 1, "proteins": 1, "muscle": 1, "muscles": 1, "gains": 1,
        "lifting": 1, "strength": 1,
    },
    "kcal": {
        "calorie": -1, "calories": -1, "kcal": -1, "light": -1, "lighter": -1,
        "weight": -1, "slim": -1, "diet": -1, "energy": 1, "bulk": 1, "bulking": 1,
    },
    "fiber": {
        "fiber": 1, "fibre": 1, "roughage": 1, "digestion": 1, "digestive": 1,
        "constipation": 1, "constipated": 1, "regular": 1,
    },
    "carbs": {
        "carb": -1, "carbs": -1, "carbohydrate": -1, "carbohydrates": -1,
        "starch": -1, "starchy": -1, "keto": -1, "bread": -1, "rice": -1,
        "pasta": -1,
    },
}
MORE = {"more", "high", "higher", "highest", "most", "max", "maximum", "extra",
        "increase", "boost", "plenty", "lots", "gain", "add"}
LESS = {"less", "low", "lower", "lowest", "least", "fewer", "fewest", "reduce",
        "cut", "cutting", "minimal", "minimum", "lose", "losing", "avoid",
        "limit", "drop"}


def detect(request: str) -> tuple[str, int] | None:
    """Return (nutrient, direction) for the first nutrient cue, or None."""

    words = re.findall(r"[a-z]+", request.lower())
    for index, word in enumerate(words):
        for nutrient, cues in NUTRIENT_CUES.items():
            if word not in cues:
                continue
            nearby = set(words[max(0, index - 4) : index + 3])
            if nearby & LESS and not nearby & MORE:
                return nutrient, -1
            if nearby & MORE and not nearby & LESS:
                return nutrient, 1
            return nutrient, cues[word]
    return None


def choose(request: str, candidates: list[dict[str, Any]]) -> int:
    """Return the 1-based number of the chosen candidate."""

    cue = detect(request)
    if cue is None:
        return 1
    nutrient, direction = cue
    best = max(direction * candidate["totals"][nutrient] for candidate in candidates)
    return next(
        candidate["number"]
        for candidate in candidates
        if direction * candidate["totals"][nutrient] == best
    )
