# Data Governance and Hybrid Cloud Flexibility - Reference Solution

This repository is organized as a productized reference implementation for governance, sovereignty, and hybrid cloud compliance scenarios across Azure, Microsoft Fabric, Purview, Power Platform, Azure Functions, and Copilot Studio.

The repo is module-driven by design. Readers start with shared foundation guidance, then choose the module they want to prepare, build, and test.

## How To Navigate This Repo

- New to the solution: start with [docs/overview/what-this-solution-is.md](docs/overview/what-this-solution-is.md), [docs/overview/architecture-overview.md](docs/overview/architecture-overview.md), and [docs/overview/module-selection-guide.md](docs/overview/module-selection-guide.md).
- Implementing one scenario: go directly to the relevant module under `modules/`, then follow `README.md` -> `dependencies.md` -> `prepare.md` -> `build.md` -> `test.md`.
- Implementing the full platform: start with [modules/module-0-foundation/README.md](modules/module-0-foundation/README.md), then implement Modules 1 through 5 in sequence.

## Solution Modules

| Module | Purpose | Action Model | Estimated Effort | Entry Point |
|---|---|---|---|---|
| 0 | Shared foundation | Readiness and platform setup | Medium | [modules/module-0-foundation/README.md](modules/module-0-foundation/README.md) |
| 1 | Resource tagging | Read-first, optional remediation | Medium | [modules/module-1-resource-tagging/README.md](modules/module-1-resource-tagging/README.md) |
| 2 | Data residency | Read-first, optional remediation | Medium | [modules/module-2-data-residency/README.md](modules/module-2-data-residency/README.md) |
| 3 | Confidential computing | Investigation plus action-enabled flows | High | [modules/module-3-confidential-computing/README.md](modules/module-3-confidential-computing/README.md) |
| 4 | Defender enablement | Read-first, optional remediation | Medium | [modules/module-4-defender-enablement/README.md](modules/module-4-defender-enablement/README.md) |
| 5 | OS patching enablement | Read-first reporting and validation | Medium | [modules/module-5-os-patching-enablement/README.md](modules/module-5-os-patching-enablement/README.md) |

## Module Dependency Matrix

| Module | Purpose | Depends on Foundation | Depends on Fabric | Depends on Purview | Depends on Power Platform | Depends on Copilot Studio |
|---|---|---:|---:|---:|---:|---:|
| 0 | Shared foundation | No | Optional | Optional | No | No |
| 1 | Resource tagging | Yes | Yes | No | Optional | Optional |
| 2 | Data residency | Yes | Yes | Yes | Optional | Optional |
| 3 | Confidential computing | Yes | Yes | Optional | Yes | Yes |
| 4 | Defender enablement | Yes | Yes | No | Optional | Optional |
| 5 | OS patching enablement | Yes | Yes | No | Optional | Optional |

## Architecture At A Glance

Use the shared architecture assets in [docs/images/README.md](docs/images/README.md). Module-specific architecture slices are documented inside each module folder.

## Repository Structure

```text
data-sov-and-hyb-cloud/
|-- docs/
|   |-- overview/
|   |-- foundation/
|   |-- reference/
|   `-- images/
|-- modules/
|-- shared/
|-- releases/
`-- .github/workflows/
```

## Shared Versus Module Content

- `modules/` is the primary reader journey and implementation playbook layer.
- `shared/` stores the reusable technical assets organized by implementation type.
- `docs/` contains shared context, foundation guidance, and reference material.
- `releases/` is reserved for module bundles and full-solution bundles.

## Security Notice

This repository contains sanitized patterns and placeholder values only.

Do not publish tenant IDs, subscription IDs, app registration IDs, real URLs, keys, internal screenshots, or customer-specific names. Use placeholders such as `<TENANT_ID>`, `<SUBSCRIPTION_ID>`, `<FUNCTION_APP_URL>`, and `<WORKSPACE_NAME>`.
