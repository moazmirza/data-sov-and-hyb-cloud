# GUI Settings For Flow - custom-connect-for-ResidencyUpdateApply

## Flow purpose
Apply a confirmed residency change.

## Settings to add in Custom Connector GUI
1. Open Data > Custom connectors > your connector > Definition.
2. Select the action with Operation ID purview_residency_update_apply.
3. Confirm method/path:
   - Method: POST
   - Path: /api/purview_residency_update_apply
4. Request schema:
   - Input fields: dataProductId, targetResidencyCode, dryRun, confirm, metadata (optional)
   - Mark required fields per your backend contract.
5. Response schema:
   - Expected payload: Apply status with action log metadata
6. Save and test this action in the Test tab.

## Validation checklist
- Connection succeeds.
- Request payload is accepted by backend.
- Response includes expected properties for this flow.
- Errors are surfaced with useful messages.

## Notes
Use this file when configuring the action in the connector GUI. Flow build steps are intentionally out of scope for this folder.
