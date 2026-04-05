# Azure Arc Reusable Artifacts

Purpose: provide a reusable and versioned baseline for Arc-connected machines using exported control-plane evidence.

Each machine folder contains only:
- `arc-machine.json`: Arc machine resource export.
- `extensions.json`: Arc machine extension resource exports.
- `policy-states.json`: policy compliance states scoped to that machine.
- `summary.md`: short operational summary (purpose, tags, OS details, and policy-derived OS patch status signal).

Machine folders:
- `i-0c2d4ca587bee1bbf/`
- `i-05c131818f13b0057/`
