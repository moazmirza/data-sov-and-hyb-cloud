# Azure Functions

Feature-oriented function layout:
- `residency-preview`
- `residency-apply`
- `cc-investigate`
- `shared`

## Local Testing

1. Copy `local.settings.template.json` to `local.settings.json`.
2. Fill local placeholder values.
3. Install dependencies from `requirements.txt`.
4. Run Functions host locally.

## Documentation Requirements Per Function

- Auth model
- Managed identity permissions
- Environment variables
- Downstream APIs called
- Expected caller (Power Automate, connector, agent)
- Sample request and response payloads
