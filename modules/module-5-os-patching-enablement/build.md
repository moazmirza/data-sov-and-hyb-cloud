# Build

## Implementation Steps

1. Ingest patch state and update readiness data into shared pipelines.
2. Build scoring logic that classifies workloads by patch status.
3. Publish report pages and optional notification paths.
4. Add follow-up automation only after read-only validation succeeds.

## Build Checks

- Patch state mapping is deterministic
- Aging windows are applied consistently
- Report totals align with source snapshots
