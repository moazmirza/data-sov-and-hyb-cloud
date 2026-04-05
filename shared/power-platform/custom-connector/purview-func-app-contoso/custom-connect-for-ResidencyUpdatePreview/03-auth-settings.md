# Auth Settings - purview_residency_update_preview

## Recommended connector auth
- Type: API Key or OAuth 2.0 (choose one model used by your function app gateway).
- If API Key: header name is commonly x-functions-key.
- If OAuth 2.0: configure tenant-specific authorize/token URLs and client credentials.

## GUI steps
1. Open connector > Security tab.
2. Select authentication type.
3. Enter parameter label and parameter name.
4. Save connector.
5. Test by creating a connection.

## Flow-specific note
This operation currently expects auth model: API key
