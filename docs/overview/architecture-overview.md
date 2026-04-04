# Architecture Overview

The solution has two layers.

## Layer 1: Common Foundation

The foundation provides shared prerequisites, identity patterns, environment setup, shared data model assumptions, and reusable implementation assets.

## Layer 2: Solution Modules

Each module is a vertical slice with its own business problem, dependencies, preparation steps, build steps, test plan, architecture slice, assets, and samples.

## Core Platform Areas

- Azure Policy for governance enforcement and signal generation
- Microsoft Fabric for ingestion, transformation, scoring, and semantic modeling
- Purview for taxonomy, governance, and metadata alignment where required
- Azure Functions for read and action workflows
- Power Platform for orchestration and user-facing automation
- Copilot Studio for guided question-and-action experiences

Use the shared diagrams in `docs/images/` and the module-specific `architecture.md` files for implementation-level detail.
