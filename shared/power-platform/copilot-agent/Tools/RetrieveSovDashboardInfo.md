# RetrieveSovDashboardInfo

## Status

- Enabled in screenshot: Yes
- Tool type: Flow

## Purpose

Returns sovereignty dashboard metrics including counts, asset totals, missing residency values, and residency-update eligibility details.

## Backing flow

- [../../flows/RetrieveSovDashboardInfo/README.md](../../flows/RetrieveSovDashboardInfo/README.md)

## Intended usage

- Direct agent tool invocation for dashboard-style answers.
- Also used inside the `Purview Residency Glossary Update Workflow` topic.

## Notes

- This is read-only.
- It provides context and eligibility information, not updates.