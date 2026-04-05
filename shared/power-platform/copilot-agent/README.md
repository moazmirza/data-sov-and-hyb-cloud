# Contoso Unified Sovereignty Agent

## Overview

This folder documents the exported Copilot agent solution for the Contoso Unified Sovereignty Agent.

At a high level, the agent is composed of four related layers:

1. The Copilot agent definition itself, including its channels and generative settings.
2. Enabled Topics that orchestrate multi-step conversational workflows.
3. Enabled Tools that the agent can call directly.
4. Supporting Power Platform flows and custom connector assets that are already documented elsewhere in this repository.

The relationship between these layers is:

- The agent receives a user request in Microsoft 365 Copilot or Teams.
- An enabled Topic may orchestrate a guided workflow with prompting, preview, and confirmation.
- An enabled Tool may be called directly by the agent for task-style execution.
- Topics and Tools ultimately rely on underlying Power Platform flows and, in some cases, the Purview custom connector or Power BI/Fabric-backed components.

## Agent summary

- Agent name: Contoso Unified Sovereignty Agent
- Export type: Managed solution
- Published channels:
  - Microsoft 365 Copilot
  - Microsoft Teams
- AI configuration highlights:
  - Generative actions enabled
  - Model knowledge enabled
  - File analysis enabled
  - Semantic search enabled
  - High content moderation

## Documented in this folder

- [Topic/README.md](Topic/README.md)
- [Tools/README.md](Tools/README.md)

These sections include only the enabled Topics and enabled Tools shown in the screenshots and confirmed by the exported solution.

## Components already documented elsewhere

- Power Platform flows: [../flows/README.md](../flows/README.md)
- Custom connector assets: [../custom-connector/purview-func-app-contoso/README.md](../custom-connector/purview-func-app-contoso/README.md)

Those assets are not duplicated here.

## Other exported components

The managed solution also contains additional components that are not added as separate entries under `Topic` or `Tools` in this folder.

### Disabled custom topics from the screenshots

- Answer Residency Questions
- Goodbye
- Greeting
- Start Over
- Thank you
- Welcome - Contoso Sovereignty

### Disabled or non-documented tool definitions from the screenshots/export

- Fetch Residency Info From Purview (disabled flow tool)
- ResidencyUpdateApply (disabled connector tool)
- ResidencyUpdatePreview (disabled connector tool)

### Other exported components captured in the solution

- System topics
- Connection references
- Workflow/component set metadata
- External agent action `Sov Data Agent Contoso`
- Action `Retrieve Residency Info`
- Connector package files for `purview-func-app-contoso`
- Flow JSON files already documented under [../flows/README.md](../flows/README.md)

## Notes

- Enabled Topics are the authoritative source for guided, multi-step workflows with branching and confirmation.
- Enabled Tools are the authoritative source for direct agent-invoked operations.
- Some disabled tools still correspond to underlying flows or connector actions that remain important implementation dependencies.