# purview-func-app-contoso Custom Connector Pack

This folder is only for building and configuring the Power Platform custom connector used by the solution flows.

It does not include flow definitions.

## What is in this folder

You have four subfolders, one per flow that uses this connector. Each subfolder contains eight artifacts:

1. `01-openapi.operation.json` - OpenAPI operation template for that flow action.
2. `02-connector-metadata.md` - Connector identity and operation registration guidance.
3. `03-auth-settings.md` - Security and connection settings to apply in the GUI.
4. `04-policy-template.json` - Optional policy template for request/response handling.
5. `05-gui-settings-for-flow.md` - Exact GUI steps to wire settings for that flow action.
6. `06-sample-request.json` - Sample request payload for GUI testing.
7. `07-sample-response.success.json` - Example success response payload.
8. `08-sample-response.error.json` - Example error response payload.

## Subfolders

- `custom-connect-for-FetchResidencyInfoFromPurview`
- `custom-connect-for-ResidencyUpdatePreview`
- `custom-connect-for-ResidencyUpdateApply`
- `custom-connect-for-Apply_CCPII_Tag_And_Notify`

## Important design note

Best practice is still one shared connector used by all four flows. These subfolders are separated so users can configure each operation cleanly and verify settings operation-by-operation.

## Create the custom connector in Power Platform (GUI)

1. Open Power Apps maker portal and choose the target environment.
2. Go to Data -> Custom connectors.
3. Select New custom connector -> Create from blank.
4. Set connector name, icon, and host details.
5. Open the Security tab and configure authentication from each flow folder's `03-auth-settings.md`.
6. Open the Definition tab.
7. Add one action per flow operation by using each folder's `01-openapi.operation.json` values:
   - Operation ID
   - Summary and description
   - Request parameters/body schema
   - Response schema
8. If required, add policy entries from each folder's `04-policy-template.json`.
9. Save connector, then open Test and create a connection.
10. Validate each operation with sample payloads before using in production flows.
11. Select Update connector so all actions are published.

## Add per-flow settings in the GUI

For each flow subfolder:

1. Open `05-gui-settings-for-flow.md`.
2. In the Custom Connector Definition tab, open the matching action.
3. Apply request parameters, body schema, and response schema exactly as documented.
4. In Security and General tabs, ensure base URL and auth match your environment.
5. Save, test, and publish.

Repeat for all four folders so all flow actions are available from one connector instance.

## Environment values you must replace

- Function app base URL
- Tenant ID / client ID / client secret (if OAuth 2.0 is used)
- API key or header names (if API key auth is used)
- Any environment-specific header defaults

Never commit real secrets in this repository.