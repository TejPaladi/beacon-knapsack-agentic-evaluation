# Experiment 6: propose and confirm in the full workflow

## Question

Experiment 5 measured identification alone. Experiment 6 asks whether the
person behind each hard-wording conversation actually receives the right,
validated plan when identification is followed by the Experiment 4 workflow.

**RQ6.** When the identification step feeds the release-gated Experiment 4
agent, does propose and confirm deliver the right person's validated plan more
often than the exact-name gate, and does any identification method let a plan
for the wrong person reach the user?

## Design

- **Requests:** the 48 Experiment 5 conversations, unchanged. A resolvable
  conversation succeeds only if a plan for the labeled person is released,
  passes validation, and exactly matches Knapsack. A conversation that must be
  clarified succeeds only if no plan is released.
- **Workflow:** the Experiment 4 agent with the release gate, its system
  prompt, tools, and eight-turn limit, using the same model as the
  identification step. The agent receives the whole conversation; the
  application adds one line to the system prompt naming the identified person
  ("The application has identified the person for this request as Becca Moore
  (persona ID NA-V)."), and every identity-dependent tool is bound to that
  person.
- **Identification methods:**
  - **Exact-name gate:** the Experiments 2 and 4 gate.
  - **Stronger rules:** the frozen Experiment 5 rule resolver.
  - **Model decides:** the model's Experiment 5 answer is used directly.
  - **Propose and confirm:** a latest message with exactly one stored full
    name is used directly; otherwise the model's answer is shown as "Did you
    mean …?". A simulated user confirms only the labeled person and declines
    anything else; a declined or missing proposal ends in a clarification.
- **Models:** Granite 4 3B, Llama 3.2 3B, and Qwen 3.5 4B, temperature 0,
  three repetitions. The identification call uses the Experiment 5 prompt and
  structured output with thinking disabled; the workflow uses the Experiment 4
  settings (1,024-token turns).
- Agent runs depend only on the conversation and the identified person, so a
  run is shared by every method that identifies the same person in the same
  repetition.

The simulated user never confirms a wrong suggestion. Real users can, so the
propose-and-confirm results are an upper bound on its safety.

## Hypotheses and decision criteria

Fixed on 4 November 2026, before any Experiment 6 run.

| ID | Hypothesis | Supported if |
| --- | --- | --- |
| H6a | Propose and confirm delivers the right person's validated plan more often than the exact-name gate. | For every model, per-case majority right-plan deliveries on the 36 resolvable conversations are higher under propose and confirm, with exact McNemar p < 0.05. |
| H6b | Propose and confirm never releases a plan for the wrong person, while letting the model decide does. | Propose and confirm has zero wrong-person releases for every model, and the model-decides method has at least one for every model (per-case majority). |

## Metrics

- **Right plan delivered** (36 resolvable conversations).
- **Wrong-person release:** a released plan for anyone other than the labeled
  person, over all 48 conversations. This is the safety metric.
- **Correct clarification** (12 conversations).
- **Identified but not delivered:** the right person was identified but the
  workflow did not release a valid plan; this separates identification
  failures from workflow failures.
- **Confirmations asked** under propose and confirm.

## Results

The runs, the report, and the verdicts are in
[results/end_to_end_comparison.md](../results/end_to_end_comparison.md):
H6b is supported and H6a is not, because the gain over the exact-name gate is
significant for Granite and Qwen but not for Llama. The sections above are
unchanged since they were committed before the first run.
