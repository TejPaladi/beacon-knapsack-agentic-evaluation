"""Experiment 5: resolve hard-wording requests to one stored persona.

Each condition reads a conversation and returns one persona ID or a
clarification. The exact-name gate and the stronger rule resolver are
deterministic; the model resolver asks a local Ollama model and restricts its
answer to the stored IDs or ``unclear`` with structured output. Scoring
compares the answer with the label and never consults a model.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from beacon_m6 import beacon_backend_path, load_personas
    from benchmark import json_safe
    from meaningful_tools_benchmark import ollama_model_digest
    from persona_policy_gate import resolve_persona_request
    from robustness_benchmark import (
        DEFAULT_BASE_URL,
        MAX_COMPLETION_TOKENS,
        git_revision,
        git_worktree_dirty,
        sha256_bytes,
    )
    from rule_persona_resolver import resolve as resolve_with_rules
except ModuleNotFoundError:
    from code.beacon_m6 import beacon_backend_path, load_personas
    from code.benchmark import json_safe
    from code.meaningful_tools_benchmark import ollama_model_digest
    from code.persona_policy_gate import resolve_persona_request
    from code.robustness_benchmark import (
        DEFAULT_BASE_URL,
        MAX_COMPLETION_TOKENS,
        git_revision,
        git_worktree_dirty,
        sha256_bytes,
    )
    from code.rule_persona_resolver import resolve as resolve_with_rules


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "data" / "hard_wording_requests.json"
RULE_RESOLVER_PATH = PROJECT_ROOT / "code" / "rule_persona_resolver.py"
RESOLVERS = ("exact_rules", "stronger_rules", "model")
MODELS = ("granite4:3b", "llama3.2:3b", "qwen3.5:4b")
CATEGORIES = (
    "exact_control",
    "nickname",
    "misspelling",
    "description",
    "earlier_turns",
    "mixed_language",
    "unknown_or_ambiguous",
    "near_miss",
)
UNCLEAR = "unclear"
TEMPERATURE = 0


def directory_text() -> str:
    lines = []
    for persona_id, persona in load_personas().items():
        preferences = persona["dietaryPreferences"]
        lines.append(
            f"- {persona_id}: {persona['name']}; diabetes: "
            f"{'yes' if preferences['diabetes'] else 'no'}; vegetarian: "
            f"{'yes' if preferences['vegetarian'] else 'no'}; daily calorie goal: "
            f"{persona['nutritionalGoals']['calories']:,}"
        )
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You identify which stored person a meal-planning conversation is about.

Stored people:
{directory_text()}

Answer with the persona_id of the person the latest user message refers to. Allow for nicknames, formal names, titles with surnames, initials, spelling mistakes, descriptions that use the stored attributes, earlier messages in the conversation, and requests that mix English with other languages.
Answer "unclear" if no stored person fits, if more than one could fit, or if a stated detail such as a different surname contradicts every stored person. Never guess."""


def answer_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "persona_id": {"type": "string", "enum": [*load_personas(), UNCLEAR]}
        },
        "required": ["persona_id"],
        "additionalProperties": False,
    }


def load_cases(path: Path = DEFAULT_DATASET) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if len(cases) != 48 or len({case["case_id"] for case in cases}) != 48:
        raise ValueError("Expected 48 uniquely identified hard-wording cases.")
    known = set(load_personas())
    for case in cases:
        if case["category"] not in CATEGORIES:
            raise ValueError(f"Unknown category in {case['case_id']}.")
        if case["messages"][-1]["role"] != "user":
            raise ValueError(f"{case['case_id']} must end with a user message.")
        resolvable = case["expected_action"] == "resolve"
        if resolvable != (case["expected_persona_id"] in known):
            raise ValueError(f"Inconsistent label in {case['case_id']}.")
    return cases


def resolve_exact(messages: list[dict[str, str]]) -> str | None:
    """The Experiments 2 and 4 identity gate, applied to every user turn."""

    text = " ".join(m["content"] for m in messages if m["role"] == "user")
    decision = resolve_persona_request(text)
    return decision.authorized_persona_id if decision.status == "resolved" else None


def call_model(base_url: str, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    root = base_url.rstrip("/").removesuffix("/v1")
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            "format": answer_schema(),
            "stream": False,
            "think": False,
            "options": {"temperature": TEMPERATURE, "num_predict": MAX_COMPLETION_TOKENS},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{root}/api/chat",
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
    return {
        "content": body["message"].get("content") or "",
        "done_reason": body.get("done_reason"),
        "prompt_tokens": int(body.get("prompt_eval_count") or 0),
        "completion_tokens": int(body.get("eval_count") or 0),
    }


def parse_answer(content: str) -> str | None:
    """Return the chosen persona ID, ``unclear``, or None for an invalid answer."""

    try:
        answer = json.loads(content).get("persona_id")
    except (json.JSONDecodeError, AttributeError):
        return None
    return answer if answer in {*load_personas(), UNCLEAR} else None


def score(case: dict[str, Any], predicted: str | None) -> dict[str, Any]:
    """Classify one answer; ``predicted`` is a persona ID or None for clarify."""

    expected = case["expected_persona_id"]
    if expected is None:
        outcome = "correct_clarification" if predicted is None else "wrong_person"
    elif predicted == expected:
        outcome = "correct_resolution"
    elif predicted is None:
        outcome = "missed_resolution"
    else:
        outcome = "wrong_person"
    return {
        "predicted_persona_id": predicted,
        "outcome": outcome,
        "correct_action": outcome in {"correct_resolution", "correct_clarification"},
        "wrong_person": outcome == "wrong_person",
    }


def run_case(
    case: dict[str, Any], resolver: str, model: str | None, base_url: str
) -> dict[str, Any]:
    started = time.perf_counter()
    record: dict[str, Any] = {
        "case_id": case["case_id"],
        "category": case["category"],
        "expected_action": case["expected_action"],
        "expected_persona_id": case["expected_persona_id"],
        "messages": case["messages"],
    }
    if resolver == "exact_rules":
        predicted = resolve_exact(case["messages"])
    elif resolver == "stronger_rules":
        decision = resolve_with_rules(case["messages"])
        predicted = decision.persona_id
        record["rule_reason"] = decision.reason
        record["rule_candidates"] = list(decision.candidates)
    else:
        response = call_model(base_url, str(model), case["messages"])
        answer = parse_answer(response["content"])
        record.update(
            {
                "raw_answer": response["content"],
                "done_reason": response["done_reason"],
                "prompt_tokens": response["prompt_tokens"],
                "completion_tokens": response["completion_tokens"],
                "invalid_answer": answer is None,
            }
        )
        predicted = None if answer in (None, UNCLEAR) else answer
    record.update(score(case, predicted))
    record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return record


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    def count(predicate: Any) -> int:
        return sum(1 for case in cases if predicate(case))

    resolvable = [c for c in cases if c["expected_action"] == "resolve"]
    hard = [c for c in resolvable if c["category"] != "exact_control"]
    return {
        "cases": len(cases),
        "correct_actions": count(lambda c: c["correct_action"]),
        "correct_resolutions": sum(c["outcome"] == "correct_resolution" for c in resolvable),
        "resolvable_cases": len(resolvable),
        "hard_correct_resolutions": sum(c["outcome"] == "correct_resolution" for c in hard),
        "hard_resolvable_cases": len(hard),
        "correct_clarifications": count(lambda c: c["outcome"] == "correct_clarification"),
        "clarify_cases": len(cases) - len(resolvable),
        "wrong_person": count(lambda c: c["wrong_person"]),
        "missed_resolutions": count(lambda c: c["outcome"] == "missed_resolution"),
        "invalid_answers": count(lambda c: c.get("invalid_answer")),
        "truncated_answers": count(lambda c: c.get("done_reason") == "length"),
        "category_correct_actions": {
            category: sum(c["correct_action"] for c in cases if c["category"] == category)
            for category in CATEGORIES
        },
        "mean_latency_ms": round(sum(c["latency_ms"] for c in cases) / len(cases), 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolver", choices=RESOLVERS, required=True)
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--repetition", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.resolver == "model") != bool(args.model):
        parser.error("--model is required for the model resolver and only for it.")

    dataset_path = args.dataset.resolve()
    cases = load_cases(dataset_path)
    observed = []
    for index, case in enumerate(cases, start=1):
        observed.append(run_case(case, args.resolver, args.model, args.base_url))
        print(f"[{index}/{len(cases)}] {case['case_id']}: {observed[-1]['outcome']}", flush=True)

    is_model = args.resolver == "model"
    result = {
        "experiment": "hard_wording_identity_resolution",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "resolver": args.resolver,
            "model": args.model,
            "model_digest": ollama_model_digest(args.base_url, args.model) if is_model else None,
            "provider": "Ollama native chat API" if is_model else "local deterministic Python",
            "temperature": TEMPERATURE if is_model else None,
            "thinking": False if is_model else None,
            "max_completion_tokens": MAX_COMPLETION_TOKENS if is_model else None,
            "repetition": args.repetition,
            "dataset": str(dataset_path.relative_to(PROJECT_ROOT)),
            "dataset_sha256": sha256_bytes(dataset_path.read_bytes()),
            "system_prompt_sha256": sha256_bytes(SYSTEM_PROMPT.encode("utf-8")),
            "answer_schema_sha256": sha256_bytes(
                json.dumps(answer_schema(), sort_keys=True).encode("utf-8")
            ),
            "rule_resolver_sha256": sha256_bytes(RULE_RESOLVER_PATH.read_bytes()),
            "repository_commit": git_revision(PROJECT_ROOT),
            "worktree_dirty": git_worktree_dirty(PROJECT_ROOT),
            "beacon_backend_commit": git_revision(beacon_backend_path()),
        },
        "summary": summarize(observed),
        "cases": observed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(json_safe(result), indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
