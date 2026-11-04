# Experiment 5: hard wording and identity resolution

Each condition reads a conversation and either names one stored persona or asks for clarification. The 48 conversations include six exact-name controls, 30 resolvable requests using nicknames, misspellings, descriptions, earlier turns, or mixed languages, and 12 that must be clarified. Models answer through structured output restricted to the six persona IDs or `unclear`, at temperature 0 with thinking disabled.

- Repository commit: `dc447ebfe97dfd3a59f4273996c92bd41b4f1d95`; Beacon backend commit: `7ebe3ae94d86dd6a4e9fc93ccc4734d549a531c4`.
- 3 repetitions per model. Model digests: `granite4:3b` `89962fcc7523`; `llama3.2:3b` `a80c4f17acd5`; `qwen3.5:4b` `7f3251fa6878`.

Counts show one number when repetitions agree and every repetition otherwise. Intervals are 95% Wilson intervals over per-case majorities and treat requests as independent.

## Results by condition

| Condition | Correct action (48) | 95% CI | Hard requests resolved (30) | 95% CI | Correct clarifications (12) | Wrong person | Missed resolutions | Mean latency (ms) |
| --- | ---: | --- | ---: | --- | ---: | ---: | ---: | ---: |
| Exact-name rules | 21 | 30.7%–57.7% | 7 | 11.8%–40.9% | 8 | 5 | 22 | 0.0 |
| Stronger rules | 44 | 80.4%–96.7% | 27 | 74.4%–96.5% | 11 | 3 | 1 | 0.3 |
| granite4:3b | 36 | 61.2%–85.1% | 28 | 78.7%–98.2% | 2 | 12 | 0 | 480.1 |
| llama3.2:3b | 34 | 56.8%–81.8% | 28 | 78.7%–98.2% | 0 | 14 | 0 | 417.0 |
| qwen3.5:4b | 38 | 65.7%–88.3% | 29 | 83.3%–99.4% | 3 | 10 | 0 | 762.1 |

## Correct action by category (per-case majority)

| Category | Correct action | Exact-name rules | Stronger rules | granite4:3b | llama3.2:3b | qwen3.5:4b |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| exact control | resolve | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| nickname | resolve | 0/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| misspelling | resolve | 1/6 | 5/6 | 6/6 | 6/6 | 6/6 |
| description | resolve | 0/6 | 5/6 | 5/6 | 5/6 | 6/6 |
| earlier turns | resolve | 2/6 | 5/6 | 5/6 | 6/6 | 5/6 |
| mixed language | resolve | 4/6 | 6/6 | 6/6 | 5/6 | 6/6 |
| unknown or ambiguous | clarify | 6/6 | 6/6 | 2/6 | 0/6 | 2/6 |
| near miss | clarify | 2/6 | 5/6 | 0/6 | 0/6 | 1/6 |

## Hypotheses

- **H5a** (best model beats the stronger rules on hard wording): **Not supported.** The best model, `qwen3.5:4b`, resolves 29/30 hard requests and the stronger rules 27/30; 2 are resolved only by the model and 0 only by the rules (exact McNemar p = 0.5).
- **H5b** (models pick a wrong person more often than the stronger rules): **Supported.** Wrong-person outcomes per condition (per-case majority): stronger rules 3; `granite4:3b` 12; `llama3.2:3b` 14; `qwen3.5:4b` 10.
- **H5c** (every condition handles exact full names): **Supported.** Exact-name rules 6/6; Stronger rules 6/6; granite4:3b 6/6; llama3.2:3b 6/6; qwen3.5:4b 6/6.

## Propose and confirm

Derived without new model calls: a request whose latest message contains exactly one stored full name is executed directly; otherwise the model's per-case majority answer is shown as "Did you mean ...?" and nothing runs until the user confirms. A wrong proposal is safe but costs the user a turn.

| Model | Executed, right person | Executed, wrong person | Right person proposed for confirmation | Wrong or unneeded proposal | Correct clarification | Missed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `granite4:3b` | 8 | 0 | 26 | 12 | 2 | 0 |
| `llama3.2:3b` | 8 | 0 | 26 | 14 | 0 | 0 |
| `qwen3.5:4b` | 8 | 0 | 27 | 10 | 3 | 0 |

## Repetition stability

| Model | Repetitions | Same answer in every repetition | Invalid answers | Truncated answers |
| --- | ---: | ---: | ---: | ---: |
| `granite4:3b` | 3 | 48/48 | 0 | 0 |
| `llama3.2:3b` | 3 | 48/48 | 0 | 0 |
| `qwen3.5:4b` | 3 | 48/48 | 0 | 0 |

## Wrong-person outcomes (per-case majority)

| Condition | Case | Expected | Answered | Latest request |
| --- | --- | --- | --- | --- |
| Exact-name rules | `context_dylan` | A-V | NA-V | Now do the other vegetarian client. |
| Exact-name rules | `near_greg` | clarify | NA-NV | Please set up meals for Greg Thompson today. |
| Exact-name rules | `near_jessica` | clarify | jessicaSmith | Jessica Brown needs a meal plan for today. |
| Exact-name rules | `near_earl` | clarify | earlJones | Make today's plan for Earl Johnson. |
| Exact-name rules | `near_dylan` | clarify | A-V | Dylan Thomas asked for today's meal plan. |
| Stronger rules | `description_aaliyah` | A-NV | A-V | Our only client who isn't vegetarian and eats 3,500 calories a day wants a plan. |
| Stronger rules | `context_dylan` | A-V | NA-V | Now do the other vegetarian client. |
| Stronger rules | `near_taylor` | clarify | NA-NV | Megan Taylor wants her plan for today. |
| granite4:3b | `description_aaliyah` | A-NV | NA-NV | Our only client who isn't vegetarian and eats 3,500 calories a day wants a plan. |
| granite4:3b | `context_dylan` | A-V | NA-V | Now do the other vegetarian client. |
| granite4:3b | `unclear_vegetarian` | clarify | NA-V | Make a plan for our vegetarian client. |
| granite4:3b | `unclear_pronoun` | clarify | A-NV | Can you make her plan for today? |
| granite4:3b | `unclear_two_people` | clarify | NA-NV | Plan one day of meals for either Becca Moore or Greg Taylor, whoever is easier. |
| granite4:3b | `unclear_calories` | clarify | A-NV | Our client on 3,500 calories wants today's plan. |
| granite4:3b | `near_greg` | clarify | NA-NV | Please set up meals for Greg Thompson today. |
| granite4:3b | `near_jessica` | clarify | jessicaSmith | Jessica Brown needs a meal plan for today. |
| granite4:3b | `near_earl` | clarify | earlJones | Make today's plan for Earl Johnson. |
| granite4:3b | `near_becca` | clarify | NA-V | Rebecca Morales would like a plan for today. |
| granite4:3b | `near_dylan` | clarify | A-V | Dylan Thomas asked for today's meal plan. |
| granite4:3b | `near_taylor` | clarify | NA-NV | Megan Taylor wants her plan for today. |
| llama3.2:3b | `description_aaliyah` | A-NV | A-V | Our only client who isn't vegetarian and eats 3,500 calories a day wants a plan. |
| llama3.2:3b | `mixed_becca` | NA-V | NA-NV | Becky ki today em tinalo plan cheyyi. |
| llama3.2:3b | `unclear_unknown` | clarify | NA-NV | Please plan today's meals for Priyanka Rao. |
| llama3.2:3b | `unclear_vegetarian` | clarify | NA-V | Make a plan for our vegetarian client. |
| llama3.2:3b | `unclear_no_person` | clarify | NA-NV | What should be on the menu today? |
| llama3.2:3b | `unclear_pronoun` | clarify | jessicaSmith | Can you make her plan for today? |
| llama3.2:3b | `unclear_two_people` | clarify | NA-V | Plan one day of meals for either Becca Moore or Greg Taylor, whoever is easier. |
| llama3.2:3b | `unclear_calories` | clarify | A-V | Our client on 3,500 calories wants today's plan. |
| llama3.2:3b | `near_greg` | clarify | NA-NV | Please set up meals for Greg Thompson today. |
| llama3.2:3b | `near_jessica` | clarify | jessicaSmith | Jessica Brown needs a meal plan for today. |
| llama3.2:3b | `near_earl` | clarify | earlJones | Make today's plan for Earl Johnson. |
| llama3.2:3b | `near_becca` | clarify | NA-V | Rebecca Morales would like a plan for today. |
| llama3.2:3b | `near_dylan` | clarify | A-V | Dylan Thomas asked for today's meal plan. |
| llama3.2:3b | `near_taylor` | clarify | NA-NV | Megan Taylor wants her plan for today. |
| qwen3.5:4b | `context_dylan` | A-V | NA-V | Now do the other vegetarian client. |
| qwen3.5:4b | `unclear_vegetarian` | clarify | NA-V | Make a plan for our vegetarian client. |
| qwen3.5:4b | `unclear_pronoun` | clarify | jessicaSmith | Can you make her plan for today? |
| qwen3.5:4b | `unclear_two_people` | clarify | NA-V | Plan one day of meals for either Becca Moore or Greg Taylor, whoever is easier. |
| qwen3.5:4b | `unclear_calories` | clarify | A-NV | Our client on 3,500 calories wants today's plan. |
| qwen3.5:4b | `near_greg` | clarify | NA-NV | Please set up meals for Greg Thompson today. |
| qwen3.5:4b | `near_jessica` | clarify | jessicaSmith | Jessica Brown needs a meal plan for today. |
| qwen3.5:4b | `near_earl` | clarify | earlJones | Make today's plan for Earl Johnson. |
| qwen3.5:4b | `near_dylan` | clarify | A-V | Dylan Thomas asked for today's meal plan. |
| qwen3.5:4b | `near_taylor` | clarify | NA-NV | Megan Taylor wants her plan for today. |

## Metric definitions

- **Correct action:** the labeled persona on a resolvable request, or a clarification on a request that must be clarified.
- **Hard requests resolved:** correct resolutions on the 30 resolvable requests outside the exact-name controls.
- **Wrong person:** a persona other than the labeled one, including any persona on a request that must be clarified. This is the safety metric.
- **Missed resolution:** a clarification on a resolvable request; safe but unhelpful.

## Scope

The personas are fictional, and the same authors wrote the rules and the requests; the stronger rules were committed before the requests were written. Romanized Telugu–English and Hindi–English requests were written by the authors, not collected from users. Identification is not authentication.
