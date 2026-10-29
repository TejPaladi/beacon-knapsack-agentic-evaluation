# Deterministic Knapsack versus LLM-only meal selection

All conditions use the same six fictional Beacon personas and the same role-eligible local catalog. Knapsack receives the stored profile and selects a one-day plan. Each LLM receives the profile and complete compact catalog, then directly selects catalog IDs without a recommendation tool or dietary pre-filter. A JSON schema enforces only requested role and catalog membership; deterministic validation and Beacon metrics run after selection.

| Selector | Safe valid plans | Hard violations | Exact Knapsack matches | Mean goodness | Quality, all cases | Quality, safe cases only | Mean nutrition fit | Mean repeated foods | Mean latency (ms) | Prompt + completion tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Beacon Knapsack | 6/6 | 0 | 6/6 (reference) | 1.000 | 0.860 | 0.860 | 0.549 | 0.0 | 183.5 | 0 |
| LLM-only `granite4:3b` | 6/6 | 0 | 0/6 | 1.000 | 0.679 | 0.679 | 0.479 | 2.0 | 4338.9 | 12966 |
| LLM-only `llama3.2:3b` | 3/6 | 4 | 0/6 | 0.981 | 0.453 | 0.906 | 0.563 | 0.0 | 4035.3 | 12942 |

## Per-persona LLM audit

| Model | Persona | Safe | Violations | Beacon quality | Nutrition fit | Repeated foods | Latency (ms) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `granite4:3b` | Earl Jones | yes | 0 | 0.712 | 0.477 | 2 | 11284.4 |
| `granite4:3b` | Jessica Smith | yes | 0 | 0.721 | 0.521 | 2 | 2960.4 |
| `granite4:3b` | Aaliyah Brooks | yes | 0 | 0.603 | 0.431 | 2 | 2961.0 |
| `granite4:3b` | Becca Moore | yes | 0 | 0.719 | 0.514 | 2 | 2951.8 |
| `granite4:3b` | Greg Taylor | yes | 0 | 0.619 | 0.509 | 2 | 2935.7 |
| `granite4:3b` | Dylan Bennet | yes | 0 | 0.701 | 0.421 | 2 | 2940.1 |
| `llama3.2:3b` | Earl Jones | yes | 0 | 0.886 | 0.429 | 0 | 10319.2 |
| `llama3.2:3b` | Jessica Smith | no | 2 | 0.000 | 0.628 | 0 | 2762.5 |
| `llama3.2:3b` | Aaliyah Brooks | yes | 0 | 0.887 | 0.434 | 0 | 2781.9 |
| `llama3.2:3b` | Becca Moore | no | 1 | 0.000 | 0.735 | 0 | 2840.4 |
| `llama3.2:3b` | Greg Taylor | yes | 0 | 0.946 | 0.731 | 0 | 2734.4 |
| `llama3.2:3b` | Dylan Bennet | no | 1 | 0.000 | 0.424 | 0 | 2773.3 |

## Interpretation

- Knapsack is the only deterministic selector in this comparison and is the six-person reference, not ground truth for the uniquely best meal.
- Granite produced six dietary-adherent plans but lower mean quality and nutrition fit than Knapsack, with repeated foods.
- Llama produced no repeated foods and slightly higher mean nutrition fit, but violated diabetes or vegetarian constraints in three personas. Beacon assigns zero overall quality to unsafe plans, lowering its all-case mean to 0.453. Its three safe plans average 0.906 quality, so the evidence does not support claiming that Knapsack has the highest conditional meal quality.
- The safe-only Llama result is based on three selected cases and must be read together with its 3/6 safety rate; it is not evidence that Llama is a better selector overall.
- Nutrition fit alone is not a safety metric: a plan can approach numeric nutrient goals while violating a stored dietary condition.
- Zero exact matches means the LLMs selected different plans; it does not by itself mean those plans were invalid.

These are Beacon's own system metrics, which were designed alongside its deterministic methods; they are not independent human judgments and may favor Knapsack's design objectives. This is a one-run, six-person simulated comparison with two small local models. It supports a preliminary architecture finding, not a clinical or population-level recommendation claim.
