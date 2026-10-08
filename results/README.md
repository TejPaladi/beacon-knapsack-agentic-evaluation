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
