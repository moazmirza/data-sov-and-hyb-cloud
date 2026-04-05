# Sanitization Map

The following replacements were applied to the exported solution artifacts.

## Connector identity and naming

- `purview-func-app-contoso` -> `purview-func-app-example`
- `new_purview-2dfunc-2dapp-2dcontoso` -> `new_purview-2dfunc-2dapp-2dexample`
- `shared_purview-2dfunc-2dapp-2dcontoso-5f17e4c99d3453d5-2b8bd80e883e2423` -> `shared_purview-2dfunc-2dapp-2dexample-aaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb`
- `new_sharedpurview2dfunc2dapp2dcontoso5f17e4c99d3453d52b8bd80e883e242_fb327` -> `new_sharedpurview2dfunc2dapp2dexampleaaaaaaaaaaaaaaaa_bbbbb`

## Host and environment identifiers

- `func-purv-contoso-gkcbavefesdqhre2.eastus2-01.azurewebsites.net` -> `func-example.azurewebsites.net`

## OAuth / Entra identifiers

- Tenant ID `30c6fd04-b13e-43b1-906e-eed50b203685` -> `00000000-0000-0000-0000-000000000000`
- Client ID `326b3829-e163-48b2-8e06-260bf2276265` -> `11111111-1111-1111-1111-111111111111`
- Resource/App ID `fec2dea8-4aa7-4903-bab4-7139a09b9056` -> `22222222-2222-2222-2222-222222222222`

## Sample payload content

- `Fabric Lakehouse - SAP - Contoso` -> `Fabric Lakehouse - ERP - ExampleCorp`

## Notes

- Structural schema and operation definitions were preserved.
- No client secrets were present in the exported solution package.
