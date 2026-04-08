# Solution Modules Overview

Use this folder as the primary implementation journey for scoped solution modules.

This location is designed to grow over time. Each module should have:
- A dedicated folder named `solution-module-<n>-<solution-name>`
- A short `README.md` in the module folder
- Clear scope boundaries (inputs, transforms, outputs, report surfaces)

## Module Catalog

| Module | Folder | Purpose | Status |
|---|---|---|---|
| Solution 1: Foundational | `solution-module-1-foundational` | Cross-cutting foundation for shared setup, contracts, and prerequisites used by downstream solution modules | Drafted |
| Solution 2: Dashboard Hydration for Residency | `solution-module-2-dashboard-hydration-residency` | End-to-end lineage of residency scoring into Compliance Dashboard visuals | Drafted |
| Solution 3: Dashboard Hydration for CC-for-PII | `solution-module-3-dashboard-hydration-cc-pii` | End-to-end lineage of CC-for-PII scoring into Compliance Dashboard visuals | Drafted |
| Solution 4: Residency Compliance via Agent | `solution-module-4-residency-compliance-via-agent` | End-to-end lineage of the Copilot topic and Power Automate flows for residency compliance actions | Drafted |
| Solution 5: CC-for-PII Compliance via Agent | `solution-module-5-cc-pii-compliance-via-agent` | End-to-end lineage of the Copilot topic and Power Automate flows that identify one eligible CC/PII resource and apply the investigation tag | Drafted |