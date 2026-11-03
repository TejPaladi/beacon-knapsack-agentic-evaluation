"""Rescore saved meaningful-tool traces with the current deterministic oracle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from meaningful_tools_benchmark import valid_tool_path
from replay_release_gate import summarize


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_bytes = args.source.read_bytes()
    source = json.loads(source_bytes)
    if source["provenance"].get("worktree_dirty"):
        raise ValueError("Refusing to rescore a dirty source run.")
    if source["summary"]["cases"] != 42:
        raise ValueError("A final rescored result requires all 42 cases.")

    result = deepcopy(source)
    result["created_at"] = datetime.now(timezone.utc).isoformat()
    for case in result["cases"]:
        case["tool_path_correct"] = valid_tool_path(
            case["successful_tools"], case["expected_tools"]
        )
        case["case_pass"] = bool(
            not case.get("api_error")
            and int(case["failed_tool_calls"]) == 0
            and case["persona_routing_correct"]
            and case["tool_path_correct"]
            and case["expected_action_correct"]
            and case.get("nutrition_selection_correct") is not False
            and case.get("exact_knapsack_fidelity") is not False
        )
    result["summary"] = summarize(result["cases"])
    provenance = result["provenance"]
    provenance["rescored_from_sha256"] = sha256_bytes(source_bytes)
    provenance["rescoring_rule"] = (
        "exact tool membership plus dependency order; independent analysis and "
        "validation siblings may occur in either order"
    )
    provenance["rescoring_script_sha256"] = sha256_bytes(Path(__file__).read_bytes())
    provenance["rescoring_commit"] = git_output("rev-parse", "HEAD")
    provenance["rescoring_worktree_dirty"] = bool(git_output("status", "--porcelain"))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
