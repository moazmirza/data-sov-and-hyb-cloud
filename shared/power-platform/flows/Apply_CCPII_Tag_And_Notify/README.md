# Apply_CCPII_Tag_And_Notify

## Purpose
Applies CC/PII investigate tag changes via the custom connector and posts notification output.

## Trigger
- Trigger name: manual
- Trigger type: Request

## Action sequence
1. RequestId
2. CCPII_ApplyInvestigateTag
3. Respond_to_the_agent
4. Post_card_in_a_chat_or_channel

## Connector dependencies
- shared_purview-2dfunc-2dapp-2dexample-aaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb (custom connector)
- shared_teams (Teams connector)

## Expected invocation pattern
- Typical caller: Copilot via Topic or Tool
- Typical input: target resources/items and tag intent
- Typical output: apply status plus notification side effects

## Notes
- This flow has both connector execution and collaboration notification behavior.
- Keep payload shape aligned with custom connector operation `azure_cc_pii_investigate_tag_apply`.
