# Prompt-only versus identity-gated meal-agent evaluation

All rows use the same 30 requests, three logical tools, Beacon backend, deterministic Knapsack recommender, temperature 0, and strict trace-based scorer. The identity-gated architecture resolves an explicit stored persona before model execution, locks identity-dependent tools to that persona, returns a deterministic clarification for unclear identity, and renders the final confirmation without an additional model turn.

| Model | Architecture | Overall passed | Valid passed | Unclear passed | Routing | Correct action | Exact fidelity | Sequence | Clarification | Unsafe Knapsack executions | Policy blocks | Mean latency (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| — | No-LLM pipeline | 30/30 | 24/24 | 6/6 | 100.0% | 100.0% | 100.0% | — | 100.0% | 0 | 0 | 146.3 |
| `granite4:3b` | Prompt-only agent | 22/30 | 22/24 | 0/6 | 91.7% | 73.3% | 91.7% | 73.3% | 0.0% | 6 | 0 | 9815.1 |
| `granite4:3b` | Identity-gated agent | 28/30 | 22/24 | 6/6 | 91.7% | 93.3% | 91.7% | 93.3% | 100.0% | 0 | 2 | 3154.7 |
| `llama3.2:1b` | Prompt-only agent | 0/30 | 0/24 | 0/6 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 0 | 0 | 3596.2 |
| `llama3.2:1b` | Identity-gated agent | 6/30 | 0/24 | 6/6 | 0.0% | 20.0% | 0.0% | 20.0% | 100.0% | 0 | 59 | 2150.2 |
| `llama3.2:3b` | Prompt-only agent | 5/30 | 5/24 | 0/6 | 20.8% | 16.7% | 20.8% | 16.7% | 50.0% | 3 | 0 | 3868.7 |
| `llama3.2:3b` | Identity-gated agent | 11/30 | 5/24 | 6/6 | 20.8% | 36.7% | 20.8% | 36.7% | 100.0% | 0 | 24 | 2809.4 |
| `phi4-mini:3.8b` | Prompt-only agent | 6/30 | 0/24 | 6/6 | 0.0% | 20.0% | 0.0% | 20.0% | 100.0% | 0 | 0 | 1992.8 |
| `phi4-mini:3.8b` | Identity-gated agent | 6/30 | 0/24 | 6/6 | 0.0% | 20.0% | 0.0% | 20.0% | 100.0% | 0 | 0 | 2001.4 |
| `qwen3.5:4b` | Prompt-only agent | 16/30 | 16/24 | 0/6 | 66.7% | 70.0% | 66.7% | 53.3% | 0.0% | 1 | 0 | 15351.0 |
| `qwen3.5:4b` | Identity-gated agent | 22/30 | 16/24 | 6/6 | 66.7% | 73.3% | 66.7% | 73.3% | 100.0% | 0 | 0 | 8953.8 |

## Aggregate result

Across five models and 150 matched model-request pairs, overall passes increased from 49/150 to 73/150. Valid recommendation workflows were unchanged at 43/120 in both architectures. Unclear-identity handling increased from 6/30 to 30/30, while unsafe Knapsack executions fell from 10 to 0. Mean per-case latency across the equally sized model runs fell from 6924.8 ms to 3813.9 ms (44.9% reduction).

Therefore, the measured improvement is an orchestration-safety and efficiency improvement, not an increase in the models' underlying tool-use capability.

## Provenance note

The ten agent results record repository commit `c36f7dfff045032d51e32c1fcaffa617c09b25e7`, the same dataset hash, and identical hashes for the original benchmark and identity-gate implementations. Their worktree-dirty flag is true because generated outputs were present while the matrix was running; source identity is fixed by the recorded commit and implementation hashes. The later no-LLM baseline records its own source commit and the same request-dataset hash.

## Matched improvement

- `granite4:3b`: 22/30 → 28/30 (+6); clarification 0.0% → 100.0%; unsafe unclear-case Knapsack executions 6 → 0.
- `llama3.2:1b`: 0/30 → 6/30 (+6); clarification 100.0% → 100.0%; unsafe unclear-case Knapsack executions 0 → 0.
- `llama3.2:3b`: 5/30 → 11/30 (+6); clarification 50.0% → 100.0%; unsafe unclear-case Knapsack executions 3 → 0.
- `phi4-mini:3.8b`: 6/30 → 6/30 (+0); clarification 100.0% → 100.0%; unsafe unclear-case Knapsack executions 0 → 0.
- `qwen3.5:4b`: 16/30 → 22/30 (+6); clarification 0.0% → 100.0%; unsafe unclear-case Knapsack executions 1 → 0.

## Valid-request outcome breakdown

Each of the 24 valid requests per model is assigned to one mutually exclusive outcome. A policy-blocked wrong argument means the model supplied an invalid identity argument and the gate prevented execution; it is still a model-compliance failure.

| Model | Architecture | Pass | Policy-blocked wrong argument | Failed tool call | No successful Knapsack call | Other |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `granite4:3b` | Prompt-only agent | 22 | 0 | 1 | 1 | 0 |
| `granite4:3b` | Identity-gated agent | 22 | 1 | 0 | 1 | 0 |
| `llama3.2:1b` | Prompt-only agent | 0 | 0 | 24 | 0 | 0 |
| `llama3.2:1b` | Identity-gated agent | 0 | 24 | 0 | 0 | 0 |
| `llama3.2:3b` | Prompt-only agent | 5 | 0 | 16 | 3 | 0 |
| `llama3.2:3b` | Identity-gated agent | 5 | 16 | 0 | 3 | 0 |
| `phi4-mini:3.8b` | Prompt-only agent | 0 | 0 | 0 | 24 | 0 |
| `phi4-mini:3.8b` | Identity-gated agent | 0 | 0 | 0 | 24 | 0 |
| `qwen3.5:4b` | Prompt-only agent | 16 | 0 | 0 | 8 | 0 |
| `qwen3.5:4b` | Identity-gated agent | 16 | 0 | 0 | 8 | 0 |

The unchanged 43/120 valid total is explained by paired behavior: the same models fail on the same valid requests in both architectures. The gate changes invalid identity arguments from backend tool errors into explicit policy blocks, but it does not repair the model's argument or force the required sequence.

## Interpretation boundary

The gate improves system-level identity handling and clarification behavior; it does not improve the language model itself. Valid requests still require the model to list personas, retrieve the resolved profile, and invoke Knapsack correctly. A blocked wrong call remains a model/tool-compliance failure. Meal selection is unchanged because Beacon Knapsack remains the only component that selects food.

The no-LLM pipeline passes all 30 current cases because every valid request contains an exact full name or unique first name and every unclear case is covered by the resolver's fixed rules. This result shows that the current dataset does not demonstrate added utility from an LLM. Typos, nicknames, contextual references, and free-form preferences require a separate language-understanding evaluation.

This is a six-person, simulated evaluation. It demonstrates a controlled architecture tradeoff, not authentication, clinical safety, or general identity resolution.
