# Evaluation inputs

`personas.json` is a small, versioned snapshot of six demonstration personas
from the compatible Beacon frontend, captured on 2026-09-30. It retains only
the values needed by this study:

- dietary restrictions and preference sliders;
- numeric nutrition goals; and
- requested meal roles for breakfast, lunch, and dinner.

These are illustrative application profiles, not recruited participant data.
The repository intentionally does not copy Beacon's food or beverage catalog.
At runtime the experiment reads that catalog through the separately installed
Beacon backend.

The evaluation fixes the plan date to `2026-01-05`; it is used for reproducible
plan output and does not alter Knapsack selection.
