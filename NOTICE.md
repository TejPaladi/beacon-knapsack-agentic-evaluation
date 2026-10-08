# External dependency and attribution

This repository contains an evaluation layer, not the Beacon application.
It does not vendor Beacon's backend, food catalog, or recommendation code.

At runtime, `code/beacon_m6.py` imports the local Beacon backend selected by
`BEACON_BACKEND` and invokes its existing Knapsack path
`gen_knapsack_rec(..., algorithm="m6")`. The experiment calls that
implementation **Beacon Knapsack**; `m6` is only its internal source label.

The compatible checkout used to produce the included result summary was:

- Beacon repository: <https://github.com/kmarren/beacon-of-hope-2>
- Commit: `7ebe3ae94d86dd6a4e9fc93ccc4734d549a531c4`

Install and use the Beacon repository according to its own terms and setup
instructions. The small `data/personas.json` file is a derived experiment
snapshot containing only the six demonstration profiles and fields needed by
this evaluation; it is not a food catalog or user data export.
