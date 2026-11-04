# Experiment 7: constrained hybrid reranking

Beacon Knapsack proposes several distinct day-plans per persona, all of which pass validation. A selector picks one for a stated preference about protein, calories, fiber, or carbohydrates, worded explicitly or as a goal. A choice satisfies the request when its total for that nutrient is the best among the candidates.

- Repository commit: `64638ab431163e5b714ccfaeb5740d00b29ba7a4`; Beacon backend commit: `7ebe3ae94d86dd6a4e9fc93ccc4734d549a531c4`.
- Distinct candidates per persona: A-NV 5, A-V 5, NA-NV 5, NA-V 5, earlJones 5, jessicaSmith 5.
- Same choice in every repetition: `granite4:3b` 48/48; `llama3.2:3b` 48/48; `qwen3.5:4b` 48/48.

## Results

| Condition | Satisfied (48) | 95% CI | Explicit (24) | Implicit (24) | Default not best | Hard violations | Mean latency (ms) |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| Knapsack default | 16 | 21.7%–47.5% | 8 | 8 | 0/32 | 0 | 107.8 |
| Keyword reranker | 39 | 68.1%–89.8% | 24 | 15 | 24/32 | 0 | 107.0 |
| granite4:3b | 31 | 50.4%–76.6% | 19 | 12 | 25/32 | 0 | 2585.0 |
| llama3.2:3b | 23 | 34.5%–61.7% | 17 | 6 | 19/32 | 0 | 2544.9 |
| qwen3.5:4b | 42 | 75.3%–94.1% | 24 | 18 | 28/32 | 0 | 3098.7 |

Counts show one number when repetitions agree and every repetition otherwise. "Default not best" counts satisfied requests among those where Knapsack's default plan is not already a best candidate, where a reranker can add value.

## Hypotheses (per-case majority)

- **H7a** (best model beats the keyword reranker on implicit wording): **Not supported.** `qwen3.5:4b` satisfies 18/24 implicit requests and the keyword reranker 15/24; 7 only by the model and 4 only by the rules (exact McNemar p = 0.549).
- **H7b** (keyword reranker at least matches the best model on explicit wording): **Supported.** Keyword reranker 24/24; best model (`qwen3.5:4b`) 24/24.
- **H7c** (every chosen plan passes validation): **Supported.** 0 hard violations across all conditions and repetitions.

## Exploratory: keyword reranker with a model fallback (per-case majority)

This combination was defined after the results were seen, so it is not a test of H7.

The keyword reranker detects no cue in 12 requests and then keeps the Knapsack default.

| Model | Satisfied (48) | Implicit (24) | Model satisfied on no-cue requests |
| --- | ---: | ---: | ---: |
| granite4:3b | 41 | 17 | 6/12 |
| llama3.2:3b | 37 | 13 | 2/12 |
| qwen3.5:4b | 44 | 20 | 9/12 |

## Unsatisfied requests (per-case majority)

| Condition | Request | Wording | Chose | Best |
| --- | --- | --- | ---: | --- |
| Keyword reranker | I'm trying to drop a few pounds before my daughter's wedding. | implicit | 1 | 3 |
| Keyword reranker | I'm recovering from surgery and my doctor wants me to help my body rebuild tissue. | implicit | 1 | 3 |
| Keyword reranker | My blood sugar spikes after big meals, so I want to keep it steady. | implicit | 1 | 4 |
| Keyword reranker | I'm training for a powerlifting meet next month. | implicit | 1 | 2, 5 |
| Keyword reranker | I want to fit back into my old jeans. | implicit | 1 | 4 |
| Keyword reranker | My gastroenterologist told me to eat more whole grains, beans, and vegetables. | implicit | 1 | 3 |
| Keyword reranker | I'm following the Atkins diet this week. | implicit | 4 | 1 |
| Keyword reranker | I'm a vegetarian athlete and want my body to repair after hard training. | implicit | 1 | 2, 5 |
| Keyword reranker | I want to help lower my cholesterol and keep my gut healthy. | implicit | 1 | 3 |
| granite4:3b | Please choose the plan with the most protein. | explicit | 3 | 1, 2, 5 |
| granite4:3b | Choose the plan with the most fiber. | explicit | 3 | 1, 2, 5 |
| granite4:3b | I'm recovering from surgery and my doctor wants me to help my body rebuild tissue. | implicit | 2 | 3 |
| granite4:3b | My doctor told me I need more roughage. | implicit | 3 | 4 |
| granite4:3b | My digestion has been sluggish this week. | implicit | 4 | 3 |
| granite4:3b | Choose the plan with the least carbohydrate. | explicit | 4 | 1 |
| granite4:3b | I'm cutting out bread, rice, and pasta for a while. | implicit | 4 | 1 |
| granite4:3b | Pick whichever day has the least calories. | explicit | 4 | 1 |
| granite4:3b | I'm on a cut this month. | implicit | 2 | 1 |
| granite4:3b | I want to stay regular. | implicit | 1 | 3 |
| granite4:3b | I want to avoid the afternoon crash I get from starchy food. | implicit | 4 | 1 |
| granite4:3b | I want to fit back into my old jeans. | implicit | 2 | 4 |
| granite4:3b | My gastroenterologist told me to eat more whole grains, beans, and vegetables. | implicit | 4 | 3 |
| granite4:3b | Please pick the plan with the smallest carbohydrate total. | explicit | 4 | 1 |
| granite4:3b | I'm following the Atkins diet this week. | implicit | 2 | 1 |
| granite4:3b | I've been overeating lately and want to make up for it today. | implicit | 2 | 1 |
| granite4:3b | I want to help lower my cholesterol and keep my gut healthy. | implicit | 1 | 3 |
| llama3.2:3b | I'm trying to drop a few pounds before my daughter's wedding. | implicit | 5 | 3 |
| llama3.2:3b | I'm trying a keto-style day. | implicit | 5 | 3 |
| llama3.2:3b | I'm recovering from surgery and my doctor wants me to help my body rebuild tissue. | implicit | 2 | 3 |
| llama3.2:3b | I had a huge dinner last night, so I want to keep today light. | implicit | 2 | 4 |
| llama3.2:3b | I'd like the highest-fiber option. | explicit | 3 | 4 |
| llama3.2:3b | My doctor told me I need more roughage. | implicit | 3 | 4 |
| llama3.2:3b | My blood sugar spikes after big meals, so I want to keep it steady. | implicit | 2 | 4 |
| llama3.2:3b | I'm training for a powerlifting meet next month. | implicit | 3 | 2, 5 |
| llama3.2:3b | Choose the plan with the least carbohydrate. | explicit | 4 | 1 |
| llama3.2:3b | I'm cutting out bread, rice, and pasta for a while. | implicit | 4 | 1 |
| llama3.2:3b | I'm getting older and want to keep my muscles strong. | implicit | 3 | 2, 5 |
| llama3.2:3b | Pick whichever day has the least calories. | explicit | 4 | 1 |
| llama3.2:3b | I'm on a cut this month. | implicit | 5 | 1 |
| llama3.2:3b | Pick whichever plan has the lowest carbs. | explicit | 4 | 1 |
| llama3.2:3b | I want to avoid the afternoon crash I get from starchy food. | implicit | 5 | 1 |
| llama3.2:3b | I want meals that help me put on lean muscle. | implicit | 3 | 2, 5 |
| llama3.2:3b | I want to fit back into my old jeans. | implicit | 3 | 4 |
| llama3.2:3b | My gastroenterologist told me to eat more whole grains, beans, and vegetables. | implicit | 4 | 3 |
| llama3.2:3b | Please pick the plan with the smallest carbohydrate total. | explicit | 4 | 1 |
| llama3.2:3b | I'm following the Atkins diet this week. | implicit | 5 | 1 |
| llama3.2:3b | Please go with the lowest-calorie plan. | explicit | 4 | 1 |
| llama3.2:3b | I've been overeating lately and want to make up for it today. | implicit | 3 | 1 |
| llama3.2:3b | I want to help lower my cholesterol and keep my gut healthy. | implicit | 5 | 3 |
| llama3.2:3b | I want the plan lowest in carbs. | explicit | 5 | 1 |
| llama3.2:3b | I'm trying to eat fewer sugars and starches. | implicit | 5 | 1 |
| qwen3.5:4b | I've started lifting weights and want to build muscle. | implicit | 3 | 1, 2, 5 |
| qwen3.5:4b | I've been a bit backed up lately. | implicit | 3 | 1, 2, 5 |
| qwen3.5:4b | I'm recovering from surgery and my doctor wants me to help my body rebuild tissue. | implicit | 4 | 3 |
| qwen3.5:4b | My digestion has been sluggish this week. | implicit | 4 | 3 |
| qwen3.5:4b | I want to stay regular. | implicit | 1 | 3 |
| qwen3.5:4b | I'm a vegetarian athlete and want my body to repair after hard training. | implicit | 1 | 2, 5 |

## Scope

Every candidate comes from Knapsack and passes validation, so safety holds by construction; the experiment measures whether a selector maps a stated preference to the right nutrient and direction. Personas with identical dietary constraints share candidate sets. The requests and the keyword reranker were written by the same authors, with the reranker committed first.
