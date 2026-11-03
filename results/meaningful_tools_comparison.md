# Meaningful Beacon tools: controlled comparison

This experiment evaluates four responsibility-based tools on the same 42 fixed requests: profile retrieval, deterministic recommendation, nutrition analysis, and violation checking. Every result uses the same committed code, dataset, and tool schemas.

| Condition | Passed | Valid tool path | Correct action | Nutrition-tool choice | Knapsack fidelity | Injected-fault detection | Unsafe releases | API/loop failures | Mean latency (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Deterministic pipeline | 38/42 | 90.5% | 92.9% | 97.2% | 100.0% | 100.0% | 0 | 0 | 264.9 |
| Prompt-only agent / granite4:3b | 24/42 | 71.4% | 57.1% | 100.0% | 100.0% | 100.0% | 6 | 0 | 4573.8 |
| Policy-gated agent (paired replay) / granite4:3b | 30/42 | 71.4% | 71.4% | 100.0% | 100.0% | 100.0% | 0 | 0 | 4573.8 |
| Prompt-only agent / llama3.2:3b | 19/42 | 61.9% | 47.6% | 88.9% | 41.7% | 100.0% | 6 | 2 | 3630.6 |
| Policy-gated agent (paired replay) / llama3.2:3b | 25/42 | 61.9% | 61.9% | 88.9% | 41.7% | 100.0% | 0 | 2 | 3630.6 |
| Prompt-only agent / qwen3.5:4b | 19/42 | 59.5% | 45.2% | 86.1% | 29.2% | 100.0% | 6 | 0 | 7843.7 |
| Policy-gated agent (paired replay) / qwen3.5:4b | 25/42 | 59.5% | 59.5% | 86.1% | 29.2% | 100.0% | 0 | 0 | 7843.7 |

## Success by request category

| Request category | Deterministic pipeline | Prompt-only agent / granite4:3b | Policy-gated agent (paired replay) / granite4:3b | Prompt-only agent / llama3.2:3b | Policy-gated agent (paired replay) / llama3.2:3b | Prompt-only agent / qwen3.5:4b | Policy-gated agent (paired replay) / qwen3.5:4b |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fault injection | 100.0% | 0.0% | 100.0% | 0.0% | 100.0% | 0.0% | 100.0% |
| indirect intent | 83.3% | 83.3% | 83.3% | 50.0% | 50.0% | 66.7% | 66.7% |
| nutrition analysis | 100.0% | 0.0% | 0.0% | 33.3% | 33.3% | 16.7% | 16.7% |
| profile only | 50.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| recommendation | 100.0% | 16.7% | 16.7% | 33.3% | 33.3% | 33.3% | 33.3% |
| restriction override | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| unclear identity | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |

## Interpretation

- The deterministic rule baseline passed 38/42. Its failures show where fixed cue matching did not capture the intended language.
- Across matched model-request pairs, prompt-only agents passed 62/126; gated agents passed 80/126.
- Prompt-only agents released 18 injected faulty plans; gated agents released 0. The gate changes release permission, not the model's tool choices or Knapsack output.
- Knapsack fidelity is evaluated across ordinary recommendation-required cases. A missing plan, wrong persona, or changed role-item assignment fails; fault-injection cases are excluded because their plans are deliberately corrupted after Knapsack.

## Metric definitions

- **Passed:** all applicable routing, tool-path, action, nutrition-selection, plan-fidelity, local-tool, and API checks pass for the case.
- **Valid tool path:** successful calls have exact required membership and respect dependencies. Profile retrieval precedes recommendation; recommendation precedes analysis and validation. Nutrition analysis and validation are independent siblings and may occur in either order. Extra, missing, or repeated calls fail.
- **Correct action:** profile requests stop after retrieval; recommendation requests release a checked safe plan; fault cases block the plan; unclear identities ask for clarification without tool access.
- **Nutrition-tool choice:** nutrition analysis is called if and only if the request asks for nutrient, goal-fit, FSA-style, or WHO-style details.
- **Knapsack fidelity:** for ordinary recommendation-required cases, a plan exists and its selected role-item IDs exactly match a fresh direct Beacon Knapsack run for the same persona. Missing plans fail; injected-fault cases are excluded.
- **Injected-fault detection:** the checker identifies a plan whose first required meal role was deliberately removed after recommendation.
- **Unsafe release:** an injected faulty plan reaches the response boundary. Lower is better; zero is required.
- **Latency:** wall-clock time for identity resolution, all model turns, and local tool execution.

## Scope

The profiles are fictional, and the experiment is a software evaluation rather than clinical validation. FSA-style and WHO-style values are application-defined aggregate proxies computed by the reused Beacon module; they are not official diagnoses or individualized medical advice.
