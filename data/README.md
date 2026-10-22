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

`robustness_requests.json` is a fixed 30-request evaluation set written for
this repository. It uses only the six fictional names above and contains no
private user data. Twenty-four requests should produce a plan: one exact-name,
one paraphrase, one first-name, and one restriction-override request per
persona. The remaining six contain an unknown, missing, or ambiguous persona
and should produce a clarification without a Knapsack call.
