# Build

## Implementation Steps

1. Deploy tagging-related policy assets from `shared/infra/platform/policy/`.
2. Configure scoring and transformation logic in the shared Fabric model area.
3. Wire report measures from `shared/semantic-model/` and `shared/reports/`.
4. Optionally enable orchestration or agent experiences if desired.

## Validation During Build

- Required tags are represented in source data
- Policy outputs map into scoring tables
- Report visuals display compliant and non-compliant states
