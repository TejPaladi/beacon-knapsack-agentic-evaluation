# Beacon Knapsack: Direct vs. Agentic Orchestration

This repository evaluates one narrow question: when Beacon's deterministic
Knapsack recommender is held fixed, can an LLM reliably orchestrate the
required profile-retrieval and recommendation steps?

```
Direct baseline:  selected persona ──────────────────> Beacon Knapsack ─> plan
Agentic setting:  plain request ─> LLM ─> tools ─────> Beacon Knapsack ─> plan
```

The LLM never selects food. In the agentic condition it must identify the
persona, retrieve that profile, and invoke the same deterministic Knapsack
pipeline used by the direct baseline. This separates **orchestration quality**
from **meal-selection quality**.

## What is included

- A thin adapter that calls Beacon's real Knapsack pipeline and existing
  quality evaluators.
- Three restricted native function-calling tools: `list_personas`,
  `get_persona`, and `run_knapsack_for_persona`.
- Six non-sensitive demonstration-profile snapshots, offline tests, a concise
  notebook, and a reviewed six-persona result report.

The Beacon backend and food catalog are **not copied** into this repository.
See [NOTICE.md](NOTICE.md) for the external dependency, source commit, and
attribution.

## Study design

All cases use the same six stored profiles, catalog scope, fixed plan date,
and Knapsack implementation.

| Condition | Input | Decision maker | Output |
| --- | --- | --- | --- |
| Direct Beacon Knapsack | selected persona ID | deterministic Beacon Knapsack | one-day meal plan |
| Agentic Knapsack | “Create a one-day meal plan for Jessica Smith.” | LLM orchestrates tools; Knapsack selects food | one-day meal plan plus tool trace |

The system prompt requests, and the evaluator scores,
`list_personas → get_persona → run_knapsack_for_persona`. The tool session
enforces the safety-critical part: the final tool refuses to run unless the
matching profile has already been retrieved. The live agent loop uses native
OpenAI-compatible function calling and standard Python HTTP, not MCP or
LangChain, so the exact tool trace is visible and easy to score.

## Metrics

| Metric | What it measures |
| --- | --- |
| Requested-role coverage | Each role requested by a persona has a returned item. |
| Exact Knapsack fidelity | Agentic role-to-item IDs exactly equal the direct Knapsack reference. |
| Required tool sequence | The agent called list, profile retrieval, then Knapsack for the intended persona. |
| Original goodness | Beacon's equal-weight mean of meal variety, role coverage, and preference-constraint scores. |
| Beacon quality score | Beacon's newer weighted quality evaluator. |
| Nutrition-goal fit | A 0–1 post-hoc closeness score for daily calories, carbs, protein, and fiber. |
| Failures and latency | Provider/API failures, retries, and end-to-end time. |

Nutrition goals are evaluated after generation. The current Knapsack selector
does not use numeric calories, carbohydrates, protein, or fiber as optimization
constraints; nutrition-goal fit therefore reports observed alignment, not a
claim that Knapsack optimized these targets.

## Result included here

The reviewed comparison is in
[results/final_knapsack_vs_agentic_quality.md](results/final_knapsack_vs_agentic_quality.md).
For the six demonstration profiles, both conditions completed all cases;
agentic output had 100% requested-role coverage, exact Knapsack fidelity, and
required tool sequence. The agentic path was slower because it includes LLM
calls and provider rate-limit waits, while recommendations were unchanged.

## Next experiment: request robustness

The next study keeps the same six fictional profiles and deterministic
Knapsack recommender, but varies the user request. Its fixed 30-case dataset
contains six cases in each successful-request category (exact name,
paraphrase, first name, and an instruction to ignore saved restrictions), plus
six invalid cases with an unknown, missing, or ambiguous persona.

The invalid cases must produce a clarification without running Knapsack. The
other 24 must route to the intended profile, follow `list → profile →
Knapsack`, and exactly reproduce the deterministic reference plan. This makes
routing accuracy, Knapsack action, plan fidelity, tool sequence, failures, and
latency objectively scoreable without an LLM judge.

Two local Ollama tool-calling models are configured for a matched comparison:
`granite4:3b` and `qwen3.5:4b`. Run them sequentially so they do not compete
for local memory:

```bash
"$BEACON_PYTHON" code/robustness_benchmark.py \
  --model granite4:3b \
  --output results/robustness_granite4_3b.json

"$BEACON_PYTHON" code/robustness_benchmark.py \
  --model qwen3.5:4b \
  --output results/robustness_qwen3_5_4b.json

"$BEACON_PYTHON" code/report_robustness.py \
  --result results/robustness_granite4_3b.json \
  --result results/robustness_qwen3_5_4b.json \
  --output results/robustness_comparison.md
```

Ollama must already be serving at `http://localhost:11434`; override it with
`--base-url` if necessary. Each raw result records the model, temperature,
dataset and prompt hashes, repository commits, tool traces, errors, and
latency. No API key is needed. See
[results/README.md](results/README.md) for the exact metric definitions.

## Setup

### 1. Obtain the compatible Beacon backend

Clone or otherwise obtain a compatible checkout of
[Beacon of Hope](https://github.com/kmarren/beacon-of-hope-2), then set up its
backend environment following that project's instructions. The reference
checkout is recorded in [NOTICE.md](NOTICE.md).

### 2. Configure paths

From this repository, point `BEACON_BACKEND` at the directory containing
Beacon's `manage.py`. Run the evaluation using the Python interpreter from
Beacon's backend environment, so Django and the catalog dependencies are
available.

```bash
export BEACON_BACKEND="/absolute/path/to/beacon-of-hope-2/backend"
export BEACON_PYTHON="$BEACON_BACKEND/.venv/bin/python"

"$BEACON_PYTHON" --version
```

If the Beacon environment has a different Python location, set
`BEACON_PYTHON` to that interpreter instead. Do not place API keys in this
repository, a notebook, or `.env.example`.

### 3. Verify the deterministic integration

These tests make no model/API calls. They check that the adapter calls Beacon's
real Knapsack and endpoint path, that results are deterministic, and that the
quality evaluators are available.

```bash
"$BEACON_PYTHON" -m unittest discover -s tests -v
```

### 4. Run the two conditions

```bash
# Deterministic reference: all six personas, no API key.
"$BEACON_PYTHON" code/benchmark.py \
  --condition direct_knapsack \
  --output results/direct_knapsack.json

# Agentic smoke test: one persona. Enter/keep the key privately in your terminal.
read -rs "GROQ_API_KEY?Paste Groq API key: "; echo
export GROQ_API_KEY
"$BEACON_PYTHON" code/benchmark.py \
  --condition agentic_knapsack --limit 1 \
  --output results/agentic_smoke.json

# Full agentic run: all six personas.
"$BEACON_PYTHON" code/benchmark.py \
  --condition agentic_knapsack \
  --output results/agentic_knapsack.json
unset GROQ_API_KEY
```

The default provider/model is Groq with `openai/gpt-oss-20b`; change it with
`--model` or `GROQ_MODEL`. A live run can encounter rate limits. The benchmark
records bounded retries and reports failures instead of treating them as a
Knapsack-quality error.

### 5. Produce a paired report

```bash
"$BEACON_PYTHON" code/report_results.py \
  --direct results/direct_knapsack.json \
  --agentic results/agentic_knapsack.json \
  --output results/direct_vs_agentic.md
```

Open `notebooks/Beacon_Knapsack_Agentic_Evaluation.ipynb` for the same workflow
with short explanations and run cells.

## Repository layout

```text
code/       adapter, native tool loop, benchmark, scoring, and report generator
data/       compact demonstration-profile snapshot and provenance
notebooks/  concise walkthrough for verification and the two conditions
results/    reviewed Markdown report; regenerated JSON is ignored
tests/      offline tests against the locally installed Beacon backend
```

## Scope and limitations

- This is an evaluation of a six-profile, one-day simulated setup; it is not a
  clinical study or a health recommendation product.
- It measures whether the LLM follows a restricted workflow, not whether it
  improves deterministic Knapsack recommendations.
- Different catalog versions or Beacon commits can produce different plans.
  Record the backend commit and environment when reporting new results.
