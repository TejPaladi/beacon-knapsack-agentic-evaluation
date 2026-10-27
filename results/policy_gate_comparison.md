# Prompt-only versus policy-gated meal-agent evaluation

All rows use the same 30 requests, three logical tools, Beacon backend, deterministic Knapsack recommender, temperature 0, and strict trace-based scorer. The policy-gated architecture resolves an explicit stored persona before model execution, locks identity-dependent tools to that persona, returns a deterministic clarification for unclear identity, and renders the final confirmation without an additional model turn.

| Model | Architecture | Overall passed | Valid passed | Unclear passed | Routing | Correct action | Exact fidelity | Sequence | Clarification | Unsafe Knapsack executions | Policy blocks | Mean latency (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `granite4:3b` | Prompt-only | 22/30 | 22/24 | 0/6 | 91.7% | 73.3% | 91.7% | 73.3% | 0.0% | 6 | 0 | 9815.1 |
| `granite4:3b` | Policy-gated | 28/30 | 22/24 | 6/6 | 91.7% | 93.3% | 91.7% | 93.3% | 100.0% | 0 | 2 | 3154.7 |
| `llama3.2:1b` | Prompt-only | 0/30 | 0/24 | 0/6 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 0 | 0 | 3596.2 |
| `llama3.2:1b` | Policy-gated | 6/30 | 0/24 | 6/6 | 0.0% | 20.0% | 0.0% | 20.0% | 100.0% | 0 | 59 | 2150.2 |
| `llama3.2:3b` | Prompt-only | 5/30 | 5/24 | 0/6 | 20.8% | 16.7% | 20.8% | 16.7% | 50.0% | 3 | 0 | 3868.7 |
| `llama3.2:3b` | Policy-gated | 11/30 | 5/24 | 6/6 | 20.8% | 36.7% | 20.8% | 36.7% | 100.0% | 0 | 24 | 2809.4 |
| `phi4-mini:3.8b` | Prompt-only | 6/30 | 0/24 | 6/6 | 0.0% | 20.0% | 0.0% | 20.0% | 100.0% | 0 | 0 | 1992.8 |
| `phi4-mini:3.8b` | Policy-gated | 6/30 | 0/24 | 6/6 | 0.0% | 20.0% | 0.0% | 20.0% | 100.0% | 0 | 0 | 2001.4 |
| `qwen3.5:4b` | Prompt-only | 16/30 | 16/24 | 0/6 | 66.7% | 70.0% | 66.7% | 53.3% | 0.0% | 1 | 0 | 15351.0 |
| `qwen3.5:4b` | Policy-gated | 22/30 | 16/24 | 6/6 | 66.7% | 73.3% | 66.7% | 73.3% | 100.0% | 0 | 0 | 8953.8 |

## Aggregate result

Across five models and 150 matched model-request pairs, overall passes increased from 49/150 to 73/150. Valid recommendation workflows were unchanged at 43/120 in both architectures. Unclear-identity handling increased from 6/30 to 30/30, while unsafe Knapsack executions fell from 10 to 0. Mean per-case latency across the equally sized model runs fell from 6924.8 ms to 3813.9 ms (44.9% reduction).

Therefore, the measured improvement is an orchestration-safety and efficiency improvement, not an increase in the models' underlying tool-use capability.

## Provenance note

All ten raw results record repository commit `c36f7dfff045032d51e32c1fcaffa617c09b25e7`, the same dataset hash, and identical hashes for the benchmark and policy-gate implementations. Their worktree-dirty flag is true because generated result files were present as untracked outputs while the matrix was running; source identity is fixed by the recorded commit and implementation hashes.

## Matched improvement

- `granite4:3b`: 22/30 → 28/30 (+6); clarification 0.0% → 100.0%; unsafe unclear-case Knapsack executions 6 → 0.
- `llama3.2:1b`: 0/30 → 6/30 (+6); clarification 100.0% → 100.0%; unsafe unclear-case Knapsack executions 0 → 0.
- `llama3.2:3b`: 5/30 → 11/30 (+6); clarification 50.0% → 100.0%; unsafe unclear-case Knapsack executions 3 → 0.
- `phi4-mini:3.8b`: 6/30 → 6/30 (+0); clarification 100.0% → 100.0%; unsafe unclear-case Knapsack executions 0 → 0.
- `qwen3.5:4b`: 16/30 → 22/30 (+6); clarification 0.0% → 100.0%; unsafe unclear-case Knapsack executions 1 → 0.

## Interpretation boundary

The gate improves system-level identity safety and clarification behavior; it does not improve the language model itself. Valid requests still require the model to list personas, retrieve the authorized profile, and invoke Knapsack correctly. A blocked wrong call remains a model/tool-compliance failure. Meal selection is unchanged because Beacon Knapsack remains the only component that selects food.

This is a six-person, simulated evaluation. It demonstrates a controlled architecture tradeoff, not clinical safety or general identity resolution.
