# ResidencyUpdatePreview_wrapped

## Purpose
Builds a safe, no-write preview for a requested residency update and returns decision-ready information to the caller.

## Trigger
- Trigger name: manual
- Trigger type: Request

## Action sequence
1. composeNormalizeExpectedCurrentResidencyCode
2. ResidencyUpdatePreview
3. composeCanPreview
4. composeConflict
5. composeNeedsChange
6. composeAction
7. composeMessage
8. composeCurrentResidencyCode
9. composeTargetResidencyCode
10. composeDataProductDisplayName
11. Respond_to_the_agent
12. composeLiveEqualsTarget

## Connector dependencies
- shared_purview-2dfunc-2dapp-2dexample-aaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb (custom connector)

## Expected invocation pattern
- Typical caller: Copilot via Topic or Tool
- Typical input: data product id, expected current residency, target residency
- Typical output: preview action plan and readiness/conflict status

## Notes
- This flow does not apply changes.
- Keep payload shape aligned with custom connector operation `purview_residency_update_preview`.
