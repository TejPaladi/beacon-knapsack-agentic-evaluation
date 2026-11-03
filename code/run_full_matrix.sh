#!/usr/bin/env bash
# Re-run Experiments 2 and 4 from a clean commit.
#
# Outputs go to OUT_DIR, outside the repository, so that writing one result
# never makes the worktree dirty for the next run. Copy OUT_DIR/meaningful_tools
# and OUT_DIR/policy_gate_matrix into results/ after every run has finished.
#
# Usage: BEACON_PYTHON=/path/to/python code/run_full_matrix.sh OUT_DIR
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${BEACON_PYTHON:?Set BEACON_PYTHON to the Beacon backend interpreter}"
OUT="${1:?usage: run_full_matrix.sh OUT_DIR}"
REPS="${REPS:-3}"
cd "$ROOT"

if [ -n "$(git status --porcelain)" ]; then
  echo "Commit or stash all changes before a final run." >&2
  exit 1
fi
case "$(cd "$(dirname "$OUT")" 2>/dev/null && pwd)/" in
  "$ROOT"/*) echo "OUT_DIR must be outside the repository." >&2; exit 1 ;;
esac

slug() { echo "$1" | tr ':.' '__'; }
run() { echo "[$(date '+%H:%M:%S')] $*"; "$PY" "$@" > /dev/null; }

for dataset in development heldout; do
  file=data/meaningful_tool_requests.json
  [ "$dataset" = heldout ] && file=data/meaningful_tool_requests_heldout.json
  dir="$OUT/meaningful_tools/$dataset"
  run code/meaningful_tools_benchmark.py --architecture deterministic_pipeline \
    --dataset "$file" --output "$dir/deterministic_pipeline.json"
  for rep in $(seq 1 "$REPS"); do
    for model in granite4:3b llama3.2:3b qwen3.5:4b; do
      for arch in meaningful_agent_prompt_only meaningful_agent_gated; do
        run code/meaningful_tools_benchmark.py --architecture "$arch" --model "$model" \
          --dataset "$file" --repetition "$rep" \
          --output "$dir/${arch}__$(slug "$model")__r${rep}.json"
      done
    done
  done
done

dir="$OUT/policy_gate_matrix"
run code/robustness_benchmark.py --architecture deterministic_pipeline \
  --output "$dir/deterministic_pipeline.json"
for model in llama3.2:1b llama3.2:3b phi4-mini:3.8b qwen3.5:4b granite4:3b; do
  for arch in ungated_agent policy_gated_agent; do
    run code/robustness_benchmark.py --architecture "$arch" --model "$model" \
      --output "$dir/${arch}__$(slug "$model").json"
  done
done
echo "[$(date '+%H:%M:%S')] Finished."
