# Data Governance and Hybrid Cloud Flexibility - Reference Solution

This repository is a modular reference implementation for governance, sovereignty, and hybrid cloud compliance across Azure, Microsoft Fabric, Purview, Azure Functions, Power Platform, and Copilot Studio.

The implementation journey is centered on `solution-modules/`, with shared technical assets under `shared/` and cross-cutting guidance under `docs/`.

## Intended Audience

- Platform engineers standing up governance and sovereignty controls.
- Data and analytics teams building compliance dashboards in Fabric/Power BI.
- Automation teams implementing Copilot + Power Platform governed action workflows.

## Start Here

1. Read the solution overview:
	- [docs/overview/what-this-solution-is.md](docs/overview/what-this-solution-is.md)
	- [docs/overview/architecture-overview.md](docs/overview/architecture-overview.md)
	- [docs/overview/module-selection-guide.md](docs/overview/module-selection-guide.md)
2. Complete the foundation module first:
	- [solution-modules/solution-module-1-foundational/README.md](solution-modules/solution-module-1-foundational/README.md)
3. Implement hydration modules (2 through 6).
4. Implement agent/action modules (7 and 8) after hydration outputs are in place.

## Implementation Paths

- Dashboard-only path: implement modules `1 -> 2 -> 3 -> 4 -> 5 -> 6`.
- Full governed-action path: implement modules `1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8`.
- Fast validation path (POC): implement module 1, then modules 2 and 3 first to validate the base dashboard scoring pipeline.

## Solution Modules

| Module | Name | Purpose | Entry Point |
|---|---|---|---|
| 1 | Foundational | Shared platform, identity, policy, tagging, Purview/Fabric/function baselines required by all downstream modules | [solution-modules/solution-module-1-foundational/README.md](solution-modules/solution-module-1-foundational/README.md) |
| 2 | Dashboard Hydration for Residency | Hydrates residency compliance scoring and reporting datasets | [solution-modules/solution-module-2-dashboard-hydration-residency/README.md](solution-modules/solution-module-2-dashboard-hydration-residency/README.md) |
| 3 | Dashboard Hydration for CC-for-PII | Hydrates confidential-compute-for-PII scoring and investigation datasets | [solution-modules/solution-module-3-dashboard-hydration-cc-pii/README.md](solution-modules/solution-module-3-dashboard-hydration-cc-pii/README.md) |
| 4 | Dashboard Hydration for Defender | Hydrates defender posture scoring into compliance summary/reporting surfaces | [solution-modules/solution-module-4-dashboard-hydration-defender/README.md](solution-modules/solution-module-4-dashboard-hydration-defender/README.md) |
| 5 | Dashboard Hydration for Tag | Hydrates tag governance scoring into compliance summary/reporting surfaces | [solution-modules/solution-module-5-dashboard-hydration-tag/README.md](solution-modules/solution-module-5-dashboard-hydration-tag/README.md) |
| 6 | Dashboard Hydration for Patch | Hydrates patch posture signals and patch compliance percentages | [solution-modules/solution-module-6-dashboard-hydration-patch/README.md](solution-modules/solution-module-6-dashboard-hydration-patch/README.md) |
| 7 | Residency Compliance via Agent | Copilot + flow workflow for governed Purview residency update (preview then apply) | [solution-modules/solution-module-7-residency-compliance-via-agent/README.md](solution-modules/solution-module-7-residency-compliance-via-agent/README.md) |
| 8 | CC-for-PII Compliance via Agent | Copilot + flow workflow for governed investigate-tag application | [solution-modules/solution-module-8-cc-pii-compliance-via-agent/README.md](solution-modules/solution-module-8-cc-pii-compliance-via-agent/README.md) |

## Dependency Flow

- Module 1 is mandatory for modules 2 through 8.
- Module 7 depends on module 2 outputs.
- Module 8 depends on module 3 outputs.
- Recommended implementation order: `1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8`.

## Expected Outcomes By Stage

- After module 1: shared identities, policies, tags, function baseline, Purview/Fabric baseline, and orchestration foundations are in place.
- After modules 2-6: compliance dashboard is hydrated with residency, CC-for-PII, defender, tag, and patch signals.
- After modules 7-8: governed Copilot workflows can preview/apply residency and investigate-tag actions with confirmation controls.

## Repository Structure

```text
data-sov-and-hyb-cloud/
|-- docs/
|   |-- overview/
|   |-- foundation/
|   |-- reference/
|   `-- images/
|-- solution-modules/
|-- shared/
|   |-- azure-policies/
|   |-- fabric/
|   |-- functions/
|   |-- infra/
|   |-- power-platform/
|   |-- reports/
|   |-- semantic-model/
|   `-- templates/
|-- releases/
`-- .github/workflows/
```

## How `shared/` and `solution-modules/` Work Together

- `solution-modules/` explains what to build and in what order.
- `shared/` stores reusable implementation assets (notebooks, function app exports, flows, connectors, policy artifacts, templates, and model/report assets).
- Each module README references the required assets in `shared/` and provides build/test guidance for that module scope.

## Additional Documentation

- Docs index: [docs/README.md](docs/README.md)
- Shared asset index: [shared/README.md](shared/README.md)
- Module catalog: [solution-modules/README.md](solution-modules/README.md)
- Security guidance: [SECURITY.md](SECURITY.md)
- Contribution guidance: [CONTRIBUTING.md](CONTRIBUTING.md)

## Main-Branch Readiness Checklist

Use this checklist before promoting from `dev` to `main`:

1. Documentation sanity:
	- Root and module READMEs reflect current folder names and module order.
	- All links resolve.
2. Security sanity:
	- No real tenant IDs, subscription IDs, client IDs, webhook URLs, personal emails, or customer names in docs/artifacts.
	- Environment-specific endpoints and IDs are replaced with placeholders.
3. Build reproducibility:
	- Module 1 baseline steps are complete and validated.
	- At least one full hydration pipeline run is successful (modules 2-6 path).
4. Agent safety:
	- Preview-before-apply path is validated for module 7.
	- Guarded confirmation flow is validated for module 8.
5. Release hygiene:
	- Relevant updates are captured in [CHANGELOG.md](CHANGELOG.md).
	- Bundles under `releases/` are current for intended publication scope.

## Release Bundles

- Use [releases/README.md](releases/README.md) for bundle packaging guidance.
- Use `releases/module-bundles/` for per-module artifacts.
- Use `releases/full-solution-bundles/` for full environment packages.

## Security Notice

This repository is sanitized and intended for reference implementation patterns.

Do not commit tenant IDs, subscription IDs, app registration IDs, real URLs, keys, internal screenshots, or customer-specific names. Use placeholders such as `<TENANT_ID>`, `<SUBSCRIPTION_ID>`, `<FUNCTION_APP_URL>`, and `<WORKSPACE_NAME>`.
