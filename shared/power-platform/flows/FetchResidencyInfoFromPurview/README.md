# FetchResidencyInfoFromPurview

## Purpose
Retrieves current Purview residency information for a data product and returns a structured response to the calling agent.

## Trigger
- Trigger name: manual
- Trigger type: Request

## Action sequence
1. GetResidency
2. Parse_JSON
3. Respond_to_the_agent

## Connector dependencies
- shared_purview-2dfunc-2dapp-2dexample-aaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb (custom connector)

## Expected invocation pattern
- Typical caller: Copilot via Topic or Tool
- Typical input: data product identifier/name
- Typical output: normalized residency value + status details

## Notes
- This flow is request/response style and optimized for synchronous agent usage.
- Keep request/response contracts aligned with the custom connector operation `purview_residency`.
