# Purview Function App Custom Connector (Sanitized Export)

This folder contains a sanitized export of the Power Platform custom connector and related flow wrappers from solution export `customconnectorexport_1_0_0_1.zip`.

## What is included

- `sanitized-export/Connector/openapi.sanitized.json`
- `sanitized-export/Connector/connectionparameters.sanitized.json`
- `sanitized-export/Connector/policytemplateinstances.sanitized.json`
- `sanitized-export/Connector/icon.sanitized.png`
- `sanitized-export/Workflows/*.json` (flow wrappers that reference the connector)
- `sanitized-export/customizations.xml`
- `sanitized-export/solution.xml`

## Recreate Steps (Manual)

1. In Power Platform, open the target environment.
2. Go to Custom connectors and select New custom connector, then Import an OpenAPI file.
3. Upload `openapi.sanitized.json`.
4. In Security, configure OAuth 2.0 to match your tenant and app registration.
5. Replace placeholder values in auth settings (tenant ID, client ID, resource URI, redirect URI path if needed).
6. Save and Update connector.
7. Create a connection for the connector.
8. Import/update flows and map connection reference to the created connector connection.

## Important

- The files are sanitized and are not deploy-ready without replacing placeholders.
- Do not commit real client secrets, tenant IDs, or production hostnames.
