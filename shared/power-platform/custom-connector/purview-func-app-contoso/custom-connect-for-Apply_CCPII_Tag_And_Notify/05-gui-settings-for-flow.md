# GUI Settings For Flow - custom-connect-for-Apply_CCPII_Tag_And_Notify

## Flow purpose
Preview or apply investigate tag updates for resources.

## Settings to add in Custom Connector GUI
1. Open Data > Custom connectors > your connector > Definition.
2. Select the action with Operation ID azure_cc_pii_investigate_tag_apply.
3. Confirm method/path:
   - Method: POST
   - Path: /api/azure_cc_pii_investigate_tag_apply
4. Request schema:
   - Input fields: items[] or single item, dryRun, confirm
   - Mark required fields per your backend contract.
5. Response schema:
   - Expected payload: Per-item status (preview/applied/error)
6. Save and test this action in the Test tab.

## Validation checklist
- Connection succeeds.
- Request payload is accepted by backend.
- Response includes expected properties for this flow.
- Errors are surfaced with useful messages.

## Notes
Use this file when configuring the action in the connector GUI. Flow build steps are intentionally out of scope for this folder.
