# Experiment 7: constrained hybrid reranking

## Question

Experiment 3 let models pick meals from the whole catalog, and one violated
stored dietary conditions. Experiment 7 tests the hybrid proposed in Section 8
of the paper: deterministic code produces only safe plans, and a selector picks
one of them to match a stated preference.

**RQ7.** When Knapsack proposes several safe plans, does a model match a stated
soft preference better than a keyword rule, and do the chosen plans stay safe?

## Order of work

1. This design, the hypotheses, and the keyword reranker
   (`code/rule_reranker.py`) with its specification tests were committed
   before any preference request was written.
2. The request set and its labels were written next, without changing the
   reranker.
3. The runner and report were written last; the runs execute from one
   committed revision.

## Candidate plans

For each persona, Beacon Knapsack plans five consecutive days (the same
method, catalog, and constraints as every other experiment). Identical days
are removed, leaving three or four distinct plans. Every candidate is checked
with `check_plan_violations` before use. Candidate 1 is the plan Knapsack
returns for a single day, which is the default. Each candidate is described by
its items per meal and its total calories, carbohydrates, protein, and fiber
from the local catalog. Personas with identical dietary constraints receive
identical candidates.

## Requests and labels

`data/preference_requests.json`: 48 requests, eight per persona. Each states
one preference over one nutrient: more protein, fewer calories, more fiber, or
fewer carbohydrates. Each preference appears once in **explicit** wording that
names the nutrient and direction, and once in **implicit** wording that states
a goal or situation instead. The label is the set of candidates with the best
value of that nutrient; ties are all correct.

## Conditions

| Condition | Description |
| --- | --- |
| Knapsack default | Always candidate 1; ignores the request. |
| Keyword reranker | `code/rule_reranker.py`: nutrient and direction keywords with common synonyms; picks the best candidate for the detected nutrient, or candidate 1 if none is detected. The declared no-LLM baseline. |
| Model reranker | Granite 4 3B, Llama 3.2 3B, and Qwen 3.5 4B see the request and the candidates with their totals and answer with one candidate number through structured output. Temperature 0, thinking disabled, three repetitions. |

## Hypotheses and decision criteria

Fixed on 4 November 2026, before the request set was written.

| ID | Hypothesis | Supported if |
| --- | --- | --- |
| H7a | On implicit wording, the best model satisfies the preference more often than the keyword reranker. | On the 24 implicit requests, the best model's per-case majority satisfied preferences exceed the keyword reranker's, with exact McNemar p < 0.05. |
| H7b | On explicit wording, the keyword reranker does at least as well as the best model. | On the 24 explicit requests, the keyword reranker satisfies at least as many preferences as the best model (per-case majority). |
| H7c | Constrained reranking stays safe. | Every plan chosen by every condition passes `check_plan_violations`. |

## Metrics

- **Preference satisfied:** the chosen candidate is in the labeled set.
- **Hard violations** of the chosen plan.
- The same on the subset where the default is not already a best candidate,
  where a reranker can add value.
- 95% Wilson intervals, exact McNemar tests, repetition stability, latency.

## Results

The runs, the report, and the verdicts are in
[results/reranking_comparison.md](../results/reranking_comparison.md): H7b and
H7c are supported and H7a is not (Qwen 18/24 vs. keyword reranker 15/24 on
goal-style wording, exact McNemar p = 0.55). The report also includes an
exploratory combination, defined after the results were seen, in which the
keyword reranker decides when it detects a cue and the model decides
otherwise. The sections above are unchanged since they were committed before
the requests were written.
