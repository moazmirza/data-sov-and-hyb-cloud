# GUI Settings For Flow - custom-connect-for-FetchResidencyInfoFromPurview

## Flow purpose
Resolve current Purview residency term for a data product.

## Settings to add in Custom Connector GUI
1. Open Data > Custom connectors > your connector > Definition.
2. Select the action with Operation ID purview_residency.
3. Confirm method/path:
   - Method: POST
   - Path: /api/purview_residency
4. Request schema:
   - Input fields: dataProductName (required), parentTermName (optional)
   - Mark required fields per your backend contract.
5. Response schema:
   - Expected payload: Current residency details and status
6. Save and test this action in the Test tab.

## Validation checklist
- Connection succeeds.
- Request payload is accepted by backend.
- Response includes expected properties for this flow.
- Errors are surfaced with useful messages.

## Notes
Use this file when configuring the action in the connector GUI. Flow build steps are intentionally out of scope for this folder.
