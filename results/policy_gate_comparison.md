# Prompt-only versus identity-gated meal-agent evaluation

All rows use the same 30 requests, three logical tools, Beacon backend, deterministic Knapsack recommender, temperature 0, and strict trace-based scorer. The identity-gated architecture resolves an explicit stored persona before model execution, locks identity-dependent tools to that persona, returns a deterministic clarification for unclear identity, and renders the final confirmation without an additional model turn.

| Model | Architecture | Overall passed | Valid passed | Unclear passed | Routing | Correct action | Exact fidelity | Sequence | Clarification | Unsafe Knapsack executions | Policy blocks | Mean latency (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| — | No-LLM pipeline | 30/30 | 24/24 | 6/6 | 100.0% | 100.0% | 100.0% | — | 100.0% | 0 | 0 | 145.8 |
| `granite4:3b` | Prompt-only agent | 22/30 | 22/24 | 0/6 | 91.7% | 73.3% | 91.7% | 73.3% | 0.0% | 6 | 0 | 8510.9 |
| `granite4:3b` | Identity-gated agent | 28/30 | 22/24 | 6/6 | 91.7% | 93.3% | 91.7% | 93.3% | 100.0% | 0 | 2 | 2529.4 |
| `llama3.2:1b` | Prompt-only agent | 0/30 | 0/24 | 0/6 | 0.0% | 0.0% | 0.0% | 0.0% | 83.3% | 0 | 0 | 16247.8 |
| `llama3.2:1b` | Identity-gated agent | 6/30 | 0/24 | 6/6 | 0.0% | 20.0% | 0.0% | 20.0% | 100.0% | 0 | 297 | 6836.6 |
| `llama3.2:3b` | Prompt-only agent | 5/30 | 5/24 | 0/6 | 20.8% | 16.7% | 20.8% | 16.7% | 50.0% | 3 | 0 | 4611.2 |
| `llama3.2:3b` | Identity-gated agent | 11/30 | 5/24 | 6/6 | 20.8% | 36.7% | 20.8% | 36.7% | 100.0% | 0 | 24 | 2596.7 |
| `phi4-mini:3.8b` | Prompt-only agent | 6/30 | 0/24 | 6/6 | 0.0% | 20.0% | 0.0% | 20.0% | 100.0% | 0 | 0 | 2458.1 |
| `phi4-mini:3.8b` | Identity-gated agent | 6/30 | 0/24 | 6/6 | 0.0% | 20.0% | 0.0% | 20.0% | 100.0% | 0 | 0 | 2027.1 |
| `qwen3.5:4b` | Prompt-only agent | 26/30 | 22/24 | 4/6 | 91.7% | 90.0% | 91.7% | 86.7% | 66.7% | 1 | 0 | 22630.0 |
| `qwen3.5:4b` | Identity-gated agent | 28/30 | 22/24 | 6/6 | 91.7% | 93.3% | 91.7% | 93.3% | 100.0% | 0 | 0 | 12857.4 |

## Aggregate result

Across five models and 150 matched model-request pairs, overall passes increased from 59/150 to 79/150. Valid recommendation workflows were unchanged at 49/120 in both architectures. Unclear-identity handling increased from 10/30 to 30/30, while unsafe Knapsack executions fell from 10 to 0. Mean per-case latency across the equally sized model runs fell from 10891.6 ms to 5369.4 ms (50.7% reduction).

Therefore, the measured improvement is an orchestration-safety and efficiency improvement, not an increase in the models' underlying tool-use capability.

## Provenance note

All 11 results record repository commit(s) `c0099d3cd9cfd4d27c518e84910e7699e4f5c354` and one request-dataset hash; 0 were produced from an uncommitted worktree. Agent runs use a completion limit of 1024 tokens, and 32 model turns reached it.

## Matched improvement

- `granite4:3b`: 22/30 → 28/30 (+6); clarification 0.0% → 100.0%; unsafe unclear-case Knapsack executions 6 → 0.
- `llama3.2:1b`: 0/30 → 6/30 (+6); clarification 83.3% → 100.0%; unsafe unclear-case Knapsack executions 0 → 0.
- `llama3.2:3b`: 5/30 → 11/30 (+6); clarification 50.0% → 100.0%; unsafe unclear-case Knapsack executions 3 → 0.
- `phi4-mini:3.8b`: 6/30 → 6/30 (+0); clarification 100.0% → 100.0%; unsafe unclear-case Knapsack executions 0 → 0.
- `qwen3.5:4b`: 26/30 → 28/30 (+2); clarification 66.7% → 100.0%; unsafe unclear-case Knapsack executions 1 → 0.

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
| `qwen3.5:4b` | Prompt-only agent | 22 | 0 | 0 | 2 | 0 |
| `qwen3.5:4b` | Identity-gated agent | 22 | 0 | 0 | 2 | 0 |

Paired by model and valid request, 49 pass in both architectures, 71 fail in both, 0 pass only with the gate, and 0 pass only without it. The gate changes invalid identity arguments from backend tool errors into explicit policy blocks, and its trusted renderer ends the run once Knapsack succeeds, but it does not repair the model's argument or force the required sequence.

## Interpretation boundary

The gate improves system-level identity handling and clarification behavior; it does not improve the language model itself. Valid requests still require the model to list personas, retrieve the resolved profile, and invoke Knapsack correctly. A blocked wrong call remains a model/tool-compliance failure. Meal selection is unchanged because Beacon Knapsack remains the only component that selects food.

The no-LLM pipeline passes all 30 current cases because every valid request contains an exact full name or unique first name and every unclear case is covered by the resolver's fixed rules. This result shows that the current dataset does not demonstrate added utility from an LLM. Typos, nicknames, contextual references, and free-form preferences require a separate language-understanding evaluation.

This is a six-person, simulated evaluation. It demonstrates a controlled architecture tradeoff, not authentication, clinical safety, or general identity resolution.
