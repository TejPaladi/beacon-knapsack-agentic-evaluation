# Meal-agent robustness: two-model comparison

This matched study gives each local model the same 30 requests and the same three tools. Beacon Knapsack is fixed and remains the only component that selects food.

| Model | Passed cases | Persona routing | Correct Knapsack action | Exact Knapsack fidelity | Tool-sequence compliance | Clarification success | API/loop failures | Failed tool calls | Mean latency (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `granite4:3b` | 22/30 | 91.7% | 73.3% | 91.7% | 73.3% | 0.0% | 0 | 4 | 8510.9 |
| `qwen3.5:4b` | 26/30 | 91.7% | 90.0% | 91.7% | 86.7% | 66.7% | 1 | 0 | 22630.0 |

A successful recommendation must route to the intended stored persona, follow `list → profile → Knapsack`, and exactly match the deterministic reference plan. A successful invalid, missing, or ambiguous case must ask for clarification without running Knapsack.

## Success rate by request category

| Request category | `granite4:3b` | `qwen3.5:4b` |
| --- | ---: | ---: |
| `ambiguous_persona` | 0.0% | 50.0% |
| `exact_name` | 100.0% | 100.0% |
| `first_name` | 100.0% | 100.0% |
| `missing_persona` | 0.0% | 100.0% |
| `paraphrase` | 100.0% | 100.0% |
| `restriction_override` | 66.7% | 66.7% |
| `unknown_persona` | 0.0% | 50.0% |

The restriction-override cases ask the agent to ignore stored restrictions. Passing means the agent still invokes Knapsack for the intended stored profile and returns the unchanged deterministic plan. These are policy-compliance checks, not general adversarial attacks. The request set and raw results store this category as `adversarial_override`; the label is kept there because each recorded run includes the request set's SHA-256.

## Key observations

- `granite4:3b` passed 22/30 cases in 8511 ms on average. It asked a usable clarification in 0/6 unclear cases and ran Knapsack in 6 of them; 0 cases ended with an empty final reply and 0 model turns hit the completion-token limit.
- `qwen3.5:4b` passed 26/30 cases in 22630 ms on average. It asked a usable clarification in 4/6 unclear cases and ran Knapsack in 1 of them; 1 cases ended with an empty final reply and 1 model turns hit the completion-token limit.
- Exact plan fidelity is evaluated only after correct persona routing. A model receives no credit for producing a valid Knapsack plan for the wrong persona.

## Scope

These are 30 fixed, non-sensitive requests over six fictional personas. The results measure routing, workflow control, plan fidelity, clarification behavior, failures, and latency. They do not establish clinical safety or meal quality beyond the existing Beacon evaluator.
