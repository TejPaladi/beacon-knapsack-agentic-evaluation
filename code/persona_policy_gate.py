"""Deterministic identity resolution and tool authorization for meal requests.

The language model may orchestrate the workflow, but it is not trusted to
authorize access to an arbitrary stored profile. This module resolves an
explicit stored name before the model runs and constrains identity-dependent
tools to that profile. Missing, unknown, or ambiguous references produce a
clarification without profile retrieval or Knapsack execution.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

try:
    from beacon_m6 import list_personas
    from benchmark import ToolSession
except ModuleNotFoundError:
    from code.beacon_m6 import list_personas
    from code.benchmark import ToolSession


@dataclass(frozen=True)
class GateDecision:
    status: str
    authorized_persona_id: str | None
    candidate_ids: tuple[str, ...]
    candidate_names: tuple[str, ...]
    clarification: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).casefold()
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", normalized))


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def resolve_persona_request(request: str) -> GateDecision:
    """Resolve exactly one explicit stored full name or unique first name."""

    normalized_request = _normalize(request)
    entries = [
        {
            "persona_id": str(persona["persona_id"]),
            "name": str(persona["name"]),
            "full": _normalize(str(persona["name"])),
            "first": _normalize(str(persona["name"]).split()[0]),
        }
        for persona in list_personas()
    ]

    full_matches = [
        entry for entry in entries if _contains_phrase(normalized_request, entry["full"])
    ]
    matches = full_matches or [
        entry for entry in entries if _contains_phrase(normalized_request, entry["first"])
    ]

    unique_matches: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in matches:
        if entry["persona_id"] not in seen:
            unique_matches.append(entry)
            seen.add(entry["persona_id"])

    candidate_ids = tuple(entry["persona_id"] for entry in unique_matches)
    candidate_names = tuple(entry["name"] for entry in unique_matches)
    if len(unique_matches) == 1:
        return GateDecision(
            status="resolved",
            authorized_persona_id=candidate_ids[0],
            candidate_ids=candidate_ids,
            candidate_names=candidate_names,
            clarification=None,
        )
    if len(unique_matches) > 1:
        return GateDecision(
            status="ambiguous",
            authorized_persona_id=None,
            candidate_ids=candidate_ids,
            candidate_names=candidate_names,
            clarification=(
                "Which stored persona should I use: " + " or ".join(candidate_names) + "?"
            ),
        )
    return GateDecision(
        status="unresolved",
        authorized_persona_id=None,
        candidate_ids=(),
        candidate_names=(),
        clarification="Which stored persona should I use for the meal plan?",
    )


class PolicyGatedToolSession(ToolSession):
    """Restrict profile and Knapsack calls to one pre-authorized persona."""

    def __init__(self, authorized_persona_id: str) -> None:
        super().__init__()
        self.authorized_persona_id = authorized_persona_id
        self.personas_listed = False
        self.policy_blocks = 0

    def _block(
        self, name: str, arguments: dict[str, Any], reason: str
    ) -> dict[str, str]:
        self.policy_blocks += 1
        self.trace.append(
            {
                "name": name,
                "arguments": arguments,
                "ok": False,
                "policy_blocked": True,
                "error": reason,
            }
        )
        return {"error": reason}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "list_personas":
            result = super().call(name, arguments)
            if self.trace and self.trace[-1].get("ok"):
                self.personas_listed = True
            return result

        if name in {"get_persona", "run_knapsack_for_persona"}:
            target = str(arguments.get("persona_id", ""))
            if target != self.authorized_persona_id:
                return self._block(
                    name,
                    arguments,
                    "Policy gate blocked a persona ID not authorized by the user request.",
                )
            if name == "get_persona" and not self.personas_listed:
                return self._block(
                    name,
                    arguments,
                    "Policy gate requires list_personas before profile retrieval.",
                )

        return super().call(name, arguments)
