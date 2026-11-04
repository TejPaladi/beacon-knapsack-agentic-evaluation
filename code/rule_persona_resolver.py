"""Stronger deterministic persona resolver for Experiment 5 (hard wording).

This is the declared no-LLM baseline for requests that refer to a person the
way users do. It was written from a general specification and committed before
the Experiment 5 requests existed, so its rules are not tuned to them.

It extends the exact-name gate with common nicknames, spelling tolerance for
capitalized names, a title or capitalized surname, two-letter initials, stored
attributes (diabetes, vegetarian, calorie goal), corrections ("I meant ...",
"not ..."), ordinals ("the second one"), and earlier user turns. It never
guesses: no candidate, or more than one, means the request needs clarifying.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

try:
    from beacon_m6 import load_personas
except ModuleNotFoundError:
    from code.beacon_m6 import load_personas


# Common English diminutives and formal forms of the stored first names.
NICKNAMES = {
    "jessica": {"jess", "jessie", "jessi", "jessy"},
    "becca": {"rebecca", "becky", "beckie", "bec", "beck", "becka"},
    "greg": {"gregory", "gregg"},
    "dylan": {"dyl"},
    "aaliyah": {"liyah"},
    "earl": set(),
}
TITLES = {"mr", "mrs", "ms", "miss", "dr", "sir", "madam"}
NEGATORS = {"not", "isnt", "except", "instead", "without"}
PREFERRERS = {"meant", "actually", "rather"}
ORDINALS = {"first": 0, "former": 0, "second": 1, "third": 2, "latter": -1, "last": -1}
# Capitalized words that commonly follow a name without being a surname.
NOT_SURNAMES = {"today", "tomorrow", "tonight", "please", "thanks", "and", "or", "for", "the", "too"}
# Ordinary words within one edit of a stored name, never treated as names.
NOT_NAMES = {"early", "ear", "earn", "pearl", "more", "moose", "brook", "tailor", "grew", "grey", "bones", "tones", "cones", "mecca"}


@dataclass(frozen=True)
class RuleDecision:
    status: str  # "resolved" or "clarify"
    persona_id: str | None
    candidates: tuple[str, ...]
    reason: str


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _tokens(text: str) -> list[tuple[str, bool]]:
    """Original-case words, each with whether punctuation follows it.

    Apostrophes are removed first, so ``Earl's`` becomes ``Earls``.
    """

    folded = _fold(text).replace("'", "").replace("’", "")
    spans = list(re.finditer(r"[A-Za-z]+", folded))
    return [
        (
            span.group(0),
            index + 1 == len(spans)
            or bool(re.search(r"[.,;:!?\n]", folded[span.end() : spans[index + 1].start()])),
        )
        for index, span in enumerate(spans)
    ]


def _words(text: str) -> list[str]:
    return [word for word, _ in _tokens(text)]


def _distance(a: str, b: str) -> int:
    """Optimal string alignment distance (Levenshtein plus adjacent swaps)."""

    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        rows[i][0] = i
    for j in range(len(b) + 1):
        rows[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[-1][-1]


def _close(word: str, name: str) -> bool:
    if len(word) < 3 or word in NOT_NAMES:
        return False
    return _distance(word, name) <= (1 if len(name) <= 5 else 2)


def _directory() -> list[dict[str, Any]]:
    people = []
    for persona_id, persona in load_personas().items():
        first, last = persona["name"].lower().split()[0], persona["name"].lower().split()[-1]
        preferences = persona["dietaryPreferences"]
        people.append(
            {
                "id": persona_id,
                "first": first,
                "last": last,
                "nicknames": NICKNAMES.get(first, set()),
                "diabetes": bool(preferences["diabetes"]),
                "vegetarian": bool(preferences["vegetarian"]),
                "vegan": bool(preferences["vegan"]),
                "calories": int(persona["nutritionalGoals"]["calories"]),
            }
        )
    return people


def _first_match(word: str, person: dict[str, Any]) -> bool:
    lowered = word.lower()
    if lowered == person["first"] or lowered in person["nicknames"]:
        return True
    return word[:1].isupper() and _close(lowered, person["first"])


def _last_match(word: str, person: dict[str, Any]) -> bool:
    lowered = word.lower()
    return lowered == person["last"] or _close(lowered, person["last"])


def _mentions(text: str, people: list[dict[str, Any]]) -> tuple[list[tuple[int, str]], set[str]]:
    """Return (position, persona ID) mentions in order and IDs whose name conflicts.

    A conflict is a matched first name followed by a capitalized word that is
    not that person's surname, as in a different person with the same first
    name.
    """

    tokens = _tokens(text)
    words = [word for word, _ in tokens]
    found: list[tuple[int, str]] = []
    conflicts: set[str] = set()
    for index, (word, boundary) in enumerate(tokens):
        following = "" if boundary else words[index + 1]
        previous = words[index - 1].lower() if index else ""
        for person in people:
            if _first_match(word, person):
                if (
                    following[:1].isupper()
                    and following.lower() not in NOT_SURNAMES
                    and not _last_match(following, person)
                    and len(following) >= 3
                ):
                    conflicts.add(person["id"])
                else:
                    found.append((index, person["id"]))
            elif _last_match(word, person) and (word[:1].isupper() or previous in TITLES):
                found.append((index, person["id"]))
    for first, last in re.findall(r"\b([A-Z])\.\s?([A-Z])\.", _fold(text)):
        for person in people:
            if person["first"][0] == first.lower() and person["last"][0] == last.lower():
                found.append((len(words), person["id"]))
    return found, conflicts


def _attributes(text: str, people: list[dict[str, Any]]) -> set[str] | None:
    """IDs consistent with every stored attribute cue, or ``None`` if there is none."""

    lowered = _fold(text).lower()
    allowed = {person["id"] for person in people}
    cued = False
    if re.search(r"\bdiabet", lowered):
        cued = True
        allowed &= {p["id"] for p in people if p["diabetes"]}
    if re.search(r"\b(?:non|not)[\s-]*veg(?:etarian)?\b", lowered):
        cued = True
        allowed &= {p["id"] for p in people if not p["vegetarian"]}
    elif re.search(r"\b(?:vegetarian|veggie)\b", lowered):
        cued = True
        allowed &= {p["id"] for p in people if p["vegetarian"]}
    if re.search(r"\bvegan\b", lowered):
        cued = True
        allowed &= {p["id"] for p in people if p["vegan"]}
    for number in re.findall(r"\b(\d{1,2}[,.]?\d{3})\s*-?\s*(?:k?cal|calorie)", lowered):
        cued = True
        target = int(number.replace(",", "").replace(".", ""))
        allowed &= {p["id"] for p in people if p["calories"] == target}
    return allowed if cued else None


def _near(words: list[str], position: int, cues: set[str], span: int = 3) -> bool:
    return any(w.lower() in cues for w in words[max(0, position - span) : position])


def resolve(messages: list[dict[str, str]]) -> RuleDecision:
    """Resolve the conversation's latest user request to one persona or clarify."""

    people = _directory()
    user_turns = [m["content"] for m in messages if m["role"] == "user"]
    if not user_turns:
        return RuleDecision("clarify", None, (), "no user request")
    latest = user_turns[-1]
    words = _words(latest)
    mentions, conflicts = _mentions(latest, people)

    earlier: list[str] = []
    for turn in reversed(user_turns[:-1]):
        turn_mentions, _ = _mentions(turn, people)
        if turn_mentions:
            earlier = list(dict.fromkeys(pid for _, pid in turn_mentions))
            break

    preferred = {pid for pos, pid in mentions if _near(words, pos, PREFERRERS)}
    negated = {pid for pos, pid in mentions if _near(words, pos, NEGATORS)}
    named = {pid for _, pid in mentions} - negated
    attributes = _attributes(latest, people)
    lowered_words = [w.lower() for w in words]

    if conflicts:
        return RuleDecision("clarify", None, tuple(sorted(conflicts)), "name conflicts with stored surname")
    if preferred:
        candidates = preferred
        reason = "correction names a person"
    elif named:
        candidates = named & attributes if attributes is not None else named
        reason = "named in latest request"
    elif attributes is not None:
        pool = set(earlier) - negated if earlier else {p["id"] for p in people} - negated
        candidates = attributes & pool if attributes & pool else attributes - negated
        reason = "stored attribute"
    elif any(w in ORDINALS for w in lowered_words) and len(earlier) >= 2:
        index = next(ORDINALS[w] for w in lowered_words if w in ORDINALS)
        candidates = {earlier[index]} if -len(earlier) <= index < len(earlier) else set()
        reason = "ordinal reference to an earlier turn"
    elif negated and earlier:
        candidates = set(earlier) - negated
        reason = "the other person from an earlier turn"
    elif earlier:
        candidates = set(earlier)
        reason = "person from an earlier turn"
    else:
        candidates = set()
        reason = "no person identified"

    ordered = tuple(sorted(candidates))
    if len(ordered) == 1:
        return RuleDecision("resolved", ordered[0], ordered, reason)
    return RuleDecision("clarify", None, ordered, reason if ordered else "no matching person")
