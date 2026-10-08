# Beacon Knapsack: Direct vs. Agentic Orchestration

Both conditions use the same six stored Beacon personas, all local Beacon catalog sources, and Beacon's existing Knapsack pipeline. The agent is not allowed to choose food; it must retrieve the profile and invoke Knapsack.

Run status: **full comparison**. Both conditions contain the same six personas.

| Condition | Completed cases | Requested-role coverage | Exact Knapsack output fidelity | Required tool sequence | Original goodness | Beacon quality score | Nutrition-goal fit | Mean end-to-end latency (ms) | Rate-limit retries | Tool-JSON retries | Provider/timeout failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Beacon+ direct Knapsack | 6/6 (complete) | 100.0% | 100.0% | N/A | 1.000 | 0.860 | 0.549 | 202.4 | N/A | N/A | 0 |
| Agentic Knapsack | 6/6 (complete) | 100.0% | 100.0% | 100.0% | 1.000 | 0.860 | 0.549 | 5706.4 | 5 | 0 | 0 |

Original goodness is Beacon's original equal-weight average of meal variety, requested-role coverage, and preference-constraint scores. Beacon quality score is the newer weighted evaluator. Nutrition-goal fit is its 0–1 nutrition component: daily calorie, carbohydrate, protein, and fiber totals are compared with the stored goals.

Interpretation: direct Knapsack is the deterministic reference. Agentic Knapsack is successful only when it selects the intended persona, retrieves that profile, calls Knapsack, and returns exactly the corresponding Knapsack plan. A lower agentic score measures orchestration failures or API failures, not a change in the deterministic recommendation.

Scope: the nutrition-goal metrics are evaluated *after* plan generation. The current Knapsack selector does not use numeric nutrition goals as optimization constraints, so these metrics report observed goal fit rather than proof that the selector optimized those goals.

Terminology note: `m6` is only the internal Beacon source identifier for this traditional Knapsack implementation; this experiment calls the recommender Knapsack.

Rate-limit note: end-to-end agent latency includes provider-imposed retry waits. The run recorded 5 retries / 23.8s total waiting; mean latency excluding that wait was 1747.2 ms.

## Agentic case audit

| Persona | Run status | Role coverage | Exact Knapsack fidelity | Required tool sequence | Original goodness | Beacon quality | Nutrition fit | Latency (ms) | Rate retries | Tool-JSON retries | Provider failure |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Earl Jones (`earlJones`) | complete | pass | pass | pass | 1.000 | 0.851 | 0.506 | 1325.1 | 0 | 0 | — |
| Jessica Smith (`jessicaSmith`) | complete | pass | pass | pass | 1.000 | 0.846 | 0.481 | 2140.1 | 0 | 0 | — |
| Aaliyah Brooks (`A-NV`) | complete | pass | pass | pass | 1.000 | 0.827 | 0.384 | 1732.2 | 0 | 0 | — |
| Becca Moore (`NA-V`) | complete | pass | pass | pass | 1.000 | 0.876 | 0.628 | 1450.5 | 0 | 0 | — |
| Greg Taylor (`NA-NV`) | complete | pass | pass | pass | 1.000 | 0.861 | 0.557 | 11753.0 | 2 | 0 | — |
| Dylan Bennet (`A-V`) | complete | pass | pass | pass | 1.000 | 0.898 | 0.740 | 15837.3 | 3 | 0 | — |

## Nutrition-goal audit (agentic observed plans)

Each entry is `actual/goal (fit)`; fit is 1.000 for an exact daily match and declines linearly with absolute deviation.

| Persona | Calories | Carbs | Protein | Fiber | Mean nutrition fit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Earl Jones (`earlJones`) | 2400.0/2400.0 kcal (1.000) | 92.0/300.0 g (0.307) | 98.0/185.0 g (0.530) | 7.1/38.0 g (0.187) | 0.506 |
| Jessica Smith (`jessicaSmith`) | 2244.0/1800.0 kcal (0.753) | 367.1/200.0 g (0.165) | 67.7/90.0 g (0.752) | 48.9/28.0 g (0.254) | 0.481 |
| Aaliyah Brooks (`A-NV`) | 1527.0/3500.0 kcal (0.436) | 51.0/438.0 g (0.116) | 71.0/82.0 g (0.866) | 4.1/35.0 g (0.117) | 0.384 |
| Becca Moore (`NA-V`) | 2184.0/2000.0 kcal (0.908) | 321.1/130.0 g (0.000) | 58.2/64.0 g (0.909) | 36.5/28.0 g (0.696) | 0.628 |
| Greg Taylor (`NA-NV`) | 1527.0/2000.0 kcal (0.763) | 51.0/130.0 g (0.392) | 71.0/66.0 g (0.924) | 4.1/28.0 g (0.146) | 0.557 |
| Dylan Bennet (`A-V`) | 2184.0/3500.0 kcal (0.624) | 321.1/438.0 g (0.733) | 58.2/90.0 g (0.647) | 36.5/35.0 g (0.957) | 0.740 |
