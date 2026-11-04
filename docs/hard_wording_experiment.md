# Experiment 5: hard wording and identity resolution

## Question

Experiments 2 and 4 found no request on which a language model beat plain code,
because every request named its person exactly. Real users refer to people
with nicknames, misspellings, descriptions, earlier messages, and mixed
languages. Experiment 5 asks:

**RQ5.** When requests refer to a stored person the way users do, does a
language model identify the right person more often than deterministic rules,
and how often does it pick the wrong person?

Identity is studied on its own because it is the step where Experiments 2 and 4
found the most dangerous failure (a plan for the wrong or an unknown person).
Once a person is identified, the rest of the workflow is the deterministic
pipeline already evaluated, so a correct identification yields the exact
Knapsack plan.

## Order of work

1. This design, the hypotheses, and the stronger rule resolver
   (`code/rule_persona_resolver.py`) with its specification tests were
   committed first, before any Experiment 5 request was written.
2. The request set and its labels were written next, without changing the
   rules.
3. The model resolver, runner, and report were written last; the runs execute
   from one committed revision.

The same authors wrote the rules and the requests. Freezing the rules first
prevents tuning them to specific requests, but it cannot remove every bias.

## Labeling rule

A request is **resolvable** when exactly one stored persona is consistent with
every cue in the conversation: names, common nicknames, plausible
misspellings, titles with surnames, initials, stored attributes (diabetes,
vegetarian, calorie goal), corrections, and references to earlier turns.
Otherwise the correct action is to **clarify**: when no persona fits, when
several fit, or when a stated detail (such as a different surname) contradicts
every candidate.

## Request set

`data/hard_wording_requests.json`: 48 conversations, six in each of eight
categories. A conversation is a list of messages; the last message is the
request to resolve.

| Category | Correct action | What it tests |
| --- | --- | --- |
| Exact control | Resolve | A stored full name, as in Experiments 2 and 4. |
| Nickname or formal name | Resolve | Diminutives, formal forms, title with surname. |
| Misspelling | Resolve | Typos in the first name, surname, or both. |
| Description | Resolve | Stored attributes, initials, or a partial cue that fits one person. |
| Earlier turns | Resolve | Pronouns, ordinals, and corrections that need earlier messages. |
| Mixed language | Resolve | Romanized Telugu–English and Hindi–English requests. |
| Unknown or ambiguous | Clarify | No match, several matches, or no person at all. |
| Near-miss name | Clarify | A stored first name with a different surname, or similar. |

## Conditions

| Condition | Description |
| --- | --- |
| Exact rules | The identity gate from Experiments 2 and 4: one stored full name or unique first name, applied to all user turns. |
| Stronger rules | `code/rule_persona_resolver.py`: the declared no-LLM baseline for this experiment. |
| Model resolver | Granite 4 3B, Llama 3.2 3B, and Qwen 3.5 4B each see the conversation and the stored directory (ID, name, diabetes and vegetarian flags, calorie goal) and must answer with one persona ID or `unclear`. Ollama structured output restricts the answer to those seven values. Temperature 0, thinking disabled, three repetitions. |
| Propose and confirm | Derived from the runs above without new model calls: a request that names exactly one stored full name is executed directly; otherwise a model's proposal is shown to the user as "Did you mean …?" and nothing is executed. |

Thinking is disabled because, at a 1,024-token limit, Qwen's reasoning used the
whole budget and returned no answer in a trial call, the same failure found in
Experiment 2. All three models therefore run without it, as in Experiment 3.

## Hypotheses and decision criteria

Fixed on 4 November 2026, before the request set was written.

| ID | Hypothesis | Supported if |
| --- | --- | --- |
| H5a | On hard wording, the best model identifies more people correctly than the stronger rules. | On the 30 resolvable requests outside the exact-control category, the best model's per-case majority correct resolutions exceed the stronger rules', with exact McNemar p < 0.05. |
| H5b | Models pick a wrong person more often than the stronger rules. | Every model has at least one wrong-person outcome (per-case majority) over all 48 requests, and each has more than the stronger rules. |
| H5c | Every condition handles exact full names. | Every condition resolves all six exact-control requests correctly. |

A **wrong-person outcome** is resolving a request to a persona other than the
labeled one, including resolving a request whose correct action is to clarify.

## Metrics

- **Correct resolution:** the resolved ID equals the label on a resolvable
  request.
- **Correct clarification:** no ID is returned on a clarify request.
- **Wrong person:** see above; the safety metric.
- **Missed resolution:** a clarification on a resolvable request; safe but
  unhelpful.
- **Correct action:** correct resolution or correct clarification, over all 48.
- For propose and confirm: requests executed correctly, correct proposals
  shown for confirmation, wrong proposals shown for confirmation, and wrong
  people executed without confirmation.
- 95% Wilson intervals, exact McNemar tests on paired requests, repetition
  stability, and latency.
