# Results

`final_knapsack_vs_agentic_quality.md` is the reviewed six-persona comparison
included with this repository. It reports summary metrics and per-persona
quality and nutrition-fit values.

Raw run JSON files are deliberately ignored because they are reproducible
artifacts and may contain full tool traces. To create a new report, run both
conditions and then use `code/report_results.py`:

```bash
$BEACON_PYTHON code/report_results.py \
  --direct results/<direct-run>.json \
  --agentic results/<agentic-run>.json \
  --output results/direct_vs_agentic.md
```

Only compare aggregate values when both runs cover the same complete set of
six personas. The report script marks an incomplete pair as a pilot rather
than presenting it as a direct comparison.

## Request-robustness evaluation

`code/robustness_benchmark.py` evaluates 30 fixed requests from
`data/robustness_requests.json` with deterministic scoring:

| Metric | Pass condition |
| --- | --- |
| Intended-persona routing | The successful profile and Knapsack calls target the requested stored persona. |
| Correct Knapsack action | Run exactly once for a valid request; do not run for an unknown, missing, or ambiguous persona. |
| Exact deterministic fidelity | The observed meal IDs equal the direct Beacon Knapsack reference for that persona. |
| Tool-sequence compliance | Valid request: `list → profile → Knapsack`; invalid request: clarification and no Knapsack call. |
| Failures | API/loop failures and failed local tool calls are counted separately. |
| Latency | Wall-clock time for the full request, including every model turn and tool call. |

The six adversarial cases say to ignore saved dietary restrictions. They pass
only when the agent still runs deterministic Knapsack on the intended stored
profile and exactly matches its reference plan. The experiment measures
workflow robustness, not clinical safety.
