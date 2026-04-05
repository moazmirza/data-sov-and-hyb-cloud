# ResidencyUpdateApply_wrapped

## Purpose
Applies a confirmed residency update and returns apply/verification status for agent consumption.

## Trigger
- Trigger name: manual
- Trigger type: Request

## Action sequence
1. Respond_to_the_agent
2. ResidencyUpdateApply
3. composeApplied
4. composeMessage
5. composeActionStatus
6. composeVerifiedMatch
7. composeConfirm
8. composeNormalizeExpectedCurrentResidencyCode
9. composeAlreadyAtTarget

## Connector dependencies
- shared_purview-2dfunc-2dapp-2dexample-aaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb (custom connector)

## Expected invocation pattern
- Typical caller: Copilot via Topic or Tool
- Typical input: data product id, target residency, confirm/dryRun values
- Typical output: apply result, verification state, and user-facing message

## Notes
- This flow performs write behavior when confirm conditions are met.
- Keep payload shape aligned with custom connector operation `purview_residency_update_apply`.
