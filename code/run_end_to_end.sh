#!/usr/bin/env bash
# Run Experiment 6 (propose and confirm end to end) from a clean commit.
#
# Outputs go to OUT_DIR, outside the repository, so that writing one result
# never makes the worktree dirty for the next run. Copy OUT_DIR/end_to_end
# into results/ after every run has finished.
#
# Usage: BEACON_PYTHON=/path/to/python code/run_end_to_end.sh OUT_DIR
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${BEACON_PYTHON:?Set BEACON_PYTHON to the Beacon backend interpreter}"
OUT="${1:?usage: run_end_to_end.sh OUT_DIR}"
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

for rep in $(seq 1 "$REPS"); do
  for model in granite4:3b llama3.2:3b qwen3.5:4b; do
    run code/end_to_end_benchmark.py --model "$model" --repetition "$rep" \
      --output "$OUT/end_to_end/$(slug "$model")__r${rep}.json"
  done
done
echo "[$(date '+%H:%M:%S')] Finished."
