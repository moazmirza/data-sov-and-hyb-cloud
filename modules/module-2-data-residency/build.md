# Build

## Implementation Steps

1. Configure residency policy and mapping assets from `shared/infra/platform/`.
2. Load reference region and classification inputs into shared data pipelines.
3. Apply scoring and semantic model logic for approved versus observed geography.
4. Expose the outcome in reports and optional agent experiences.

## Build Checks

- Approved region mappings are loaded
- Unknown geography states are handled explicitly
- Report views separate compliant, non-compliant, and unclassified resources
