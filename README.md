# Contoso Sovereignty and Compliance Reference Solution

A reusable reference implementation showing how to combine Azure, Microsoft Fabric, Purview, Power Platform, Azure Functions, and Copilot Studio to build governance reporting and guided remediation scenarios.

## What This Repository Solves

- Residency compliance visibility
- Tagging compliance monitoring
- Confidential computing controls for PII workloads
- Defender posture reporting
- Patch and update reporting
- Guided remediation through agent actions

## Architecture at a Glance

Use the architecture diagram in `docs/images/architecture-diagram.png`.

## Solution Components

- Azure Policy definitions, initiatives, and assignment samples
- Purview setup guidance and governance dependencies
- Fabric Lakehouse ingestion, transformations, scoring, and semantic models
- Power BI report documentation
- Azure Functions for remediation preview and apply actions
- Power Automate flows and connector documentation
- Copilot Studio instructions, topics, and tool patterns

## Scenarios Included

- [Residency Compliance](docs/04-scenarios/residency-compliance.md)
- [Tagging Compliance](docs/04-scenarios/tagging-compliance.md)
- [Confidential Compute and PII](docs/04-scenarios/confidential-compute-pii.md)
- [Defender Compliance](docs/04-scenarios/defender-compliance.md)
- [Patching and Reporting](docs/04-scenarios/patching-reporting.md)

## Deployment Path

1. Deploy Azure foundation.
2. Configure identities and permissions.
3. Set up Purview artifacts.
4. Deploy Azure Function assets.
5. Import Fabric artifacts.
6. Configure semantic model and reports.
7. Import Power Platform solution content.
8. Configure Copilot Studio topics and tools.
9. Load sample data.
10. Validate end-to-end scenario flows.

## Documentation Reading Order

1. Overview (`docs/01-overview`)
2. Architecture (`docs/01-overview/architecture.md`)
3. Prerequisites (`docs/02-prerequisites`)
4. Deployment order (`docs/03-deployment/deployment-order.md`)
5. Data model (`docs/06-data-model`)
6. Scenario walkthroughs (`docs/04-scenarios`)
7. Agent actions (`docs/05-agent-actions`)
8. Troubleshooting (`docs/07-operations`)
9. Extending scenarios (`docs/07-operations/how-to-create-a-new-scenario.md`)

## Quick Start

1. Read `docs/02-prerequisites/setup-checklist.md`.
2. Populate values in `templates/env.template` and `templates/config.template.json`.
3. Follow `docs/03-deployment/deployment-order.md`.
4. Start with one scenario: `docs/04-scenarios/residency-compliance.md`.

## Security Notice

This repository is designed for sanitized examples and reusable patterns.

Do not commit tenant IDs, subscription IDs, API keys, real resource names, production exports, or internal screenshots. Use placeholders such as `<TENANT_ID>`, `<SUBSCRIPTION_ID>`, and `<FUNCTION_APP_URL>`.

## Repository Structure

```text
contoso-sovereignty-compliance-reference/
|-- docs/
|-- infra/
|-- src/
|-- samples/
|-- templates/
|-- scripts/
`-- .github/workflows/
```
