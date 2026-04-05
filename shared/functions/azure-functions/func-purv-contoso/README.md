# func-purv-contoso Sanitized Export

This folder contains a sanitized export of the Azure Functions app source retrieved from admin VFS.

## Included files
- function_app.py
- host.json
- requirements.txt

## Functions discovered
| Function name | Purpose |
|---|---|
| purview_residency | Resolve current Purview residency term for a data product. |
| purview_residency_update_preview | Build a no-write preview plan for a Purview residency change. |
| purview_residency_update_apply | Apply a confirmed Purview residency change with safeguards. |
| azure_tag_compliance | Evaluate Azure tag-based compliance signals for Data Product IDs. |
| azure_residency_compliance | Return Azure resource locations per Data Product ID for residency scoring. |
| azure_cc_for_pii_compliance | Collect confidential compute and patch evidence for VM-class assets. |
| azure_cc_pii_investigate_tag_apply | Preview/apply investigate tag updates on Azure resources. |
| azure_defender_compliance | Calculate Defender posture scoring from pricing, assessments, and alerts. |
| azure_residency_compliance_aws | Read AWS S3 bucket residency and tags for cross-cloud residency checks. |

### purview_residency
Purpose:
- Resolves the current Purview residency term for a given data product name.

High-level flow:
1. Accept `dataProductName` (required) and optional `parentTermName` from query or JSON body.
2. Resolve the data product and linked residency glossary term in Purview.
3. If a residency term is missing, return a structured "missing residency" response.
4. Normalize the residency value and return a consistent JSON payload.

App settings used:

| App setting | Required | Used for |
|---|---|---|
| PURVIEW_ENDPOINT | Yes | Base URL for Purview data-plane API calls. |
| PURVIEW_API_VERSION | Yes | API version used for Purview requests. |
| RESIDENCY_PARENT_TERM_NAME | Optional | Default parent glossary term when parentTermName is not provided in request. |
| HTTP_TIMEOUT | Optional | Timeout (seconds) for outbound HTTP requests. |

### purview_residency_update_preview
Purpose:
- Produces a safe, non-writing preview plan before any Purview residency change.

High-level flow:
1. Parse request payload (data product ID, target residency code, expected current residency, metadata).
2. Validate request shape and prerequisites (target term lookup, current state checks).
3. Build a plan showing what relationships would be removed/added.
4. Return preview details and status code without mutating Purview.

App settings used:

| App setting | Required | Used for |
|---|---|---|
| PURVIEW_ENDPOINT | Yes | Reads data product and glossary term relationships in preview plan. |
| PURVIEW_API_VERSION | Yes | Version for Purview lookup APIs used during preview. |
| RESIDENCY_PARENT_TERM_NAME | Optional | Default parent term for residency resolution if omitted by caller. |
| HTTP_TIMEOUT | Optional | Timeout control for Purview REST calls. |

### purview_residency_update_apply
Purpose:
- Applies the Purview residency update plan with explicit confirmation controls.

High-level flow:
1. Parse request and enforce safe defaults (`dryRun=true` unless explicitly disabled).
2. Require explicit confirmation (`confirm=true`) for real writes.
3. Remove old residency relationship(s) and create the new relationship when applicable.
4. Emit action-log/changelog metadata (best effort) and return final status + details.

App settings used:

| App setting | Required | Used for |
|---|---|---|
| PURVIEW_ENDPOINT | Yes | Reads and writes Purview glossary term relationships. |
| PURVIEW_API_VERSION | Yes | API version for Purview mutation and verification calls. |
| RESIDENCY_PARENT_TERM_NAME | Optional | Default parent term when not explicitly supplied. |
| HTTP_TIMEOUT | Optional | Timeout control for Purview API operations. |
| FABRIC_SQL_LOGGING_ENABLED | Optional | Enables best-effort apply/audit logging to Fabric SQL. |
| FABRIC_SQL_SERVER | Optional | Fabric SQL server endpoint for action log insert. |
| FABRIC_SQL_DATABASE | Optional | Fabric SQL database for action log insert. |
| FABRIC_SQL_DRIVER | Optional | ODBC driver used for SQL connection. |
| FABRIC_CHANGELOG_TABLE_PURVIEW | Optional | Purview action log table name. |

### azure_tag_compliance
Purpose:
- Evaluates tag-based compliance per Data Product ID across Azure resources.

High-level flow:
1. Parse and validate `dataProductIds` and `subscriptions`.
2. Query Azure Resource Graph for resources tagged with matching `dataproductid`.
3. Read observed tag signals (`resource-origin`, `sovereignty-zone`).
4. Score each Data Product ID and return matched/missing breakdowns.

App settings used:

| App setting | Required | Used for |
|---|---|---|
| AZURE_SUBSCRIPTIONS | Optional | Default subscription list when subscriptions are not passed in the request. |
| RESOURCE_GRAPH_API_VERSION | Yes | API version for Azure Resource Graph queries. |
| HTTP_TIMEOUT | Optional | Timeout for Resource Graph and ARM HTTP calls. |
| ARM_TENANT_B_TENANT_ID | Optional | Enables cross-tenant ARM/ARG auth profile when configured with matching tenant B settings. |
| ARM_TENANT_B_CLIENT_ID | Optional | Service principal client ID for cross-tenant profile. |
| ARM_TENANT_B_CLIENT_SECRET | Optional | Service principal secret for cross-tenant profile. |
| ARM_TENANT_B_SUBSCRIPTIONS | Optional | Comma-separated subscriptions to route through cross-tenant profile. |

### azure_residency_compliance
Purpose:
- Returns all resource locations for each Data Product ID so downstream systems can score residency.

High-level flow:
1. Parse and validate `dataProductIds` and `subscriptions`.
2. Query Resource Graph for tag matches using common `DataProductId` tag variants.
3. Group resources by Data Product ID and derive distinct location codes.
4. Return per-ID resource lists, location sets, and missing IDs.

App settings used:

| App setting | Required | Used for |
|---|---|---|
| AZURE_SUBSCRIPTIONS | Optional | Default subscriptions fallback when not provided by caller. |
| RESOURCE_GRAPH_API_VERSION | Yes | API version used for residency Resource Graph queries. |
| HTTP_TIMEOUT | Optional | Timeout for Resource Graph calls. |
| ARM_TENANT_B_TENANT_ID | Optional | Cross-tenant auth toggle for selected subscriptions. |
| ARM_TENANT_B_CLIENT_ID | Optional | Cross-tenant service principal client ID. |
| ARM_TENANT_B_CLIENT_SECRET | Optional | Cross-tenant service principal secret. |
| ARM_TENANT_B_SUBSCRIPTIONS | Optional | Subscription routing list for cross-tenant profile. |

### azure_cc_for_pii_compliance
Purpose:
- Collects Confidential Compute and patch-assessment signals for VM-like assets tied to each Data Product ID.

High-level flow:
1. Parse and validate `dataProductIds` and `subscriptions`.
2. Query Resource Graph for tagged resources and prioritize VM/Arc/SQL VM resource types.
3. Derive CC lookup SKU from ARG first, with ARM fallback for missing VM details.
4. Pull patch assessment summaries from Update Manager ARG tables.
5. Return per-ID compliance evidence (resource kind, lookup SKU source, patch status, details).

App settings used:

| App setting | Required | Used for |
|---|---|---|
| AZURE_SUBSCRIPTIONS | Optional | Default subscription list fallback. |
| RESOURCE_GRAPH_API_VERSION | Yes | API version for ARG resource and patchassessmentresources queries. |
| VM_API_VERSION | Optional | ARM API version for VM details fallback lookups. |
| HTTP_TIMEOUT | Optional | Timeout for ARG and ARM calls. |
| ARM_TENANT_B_TENANT_ID | Optional | Cross-tenant auth enablement for selected subscriptions. |
| ARM_TENANT_B_CLIENT_ID | Optional | Cross-tenant service principal client ID. |
| ARM_TENANT_B_CLIENT_SECRET | Optional | Cross-tenant service principal secret. |
| ARM_TENANT_B_SUBSCRIPTIONS | Optional | Subscription list mapped to cross-tenant profile. |

### azure_cc_pii_investigate_tag_apply
Purpose:
- Applies (or previews) an investigate/compliance tag update to one or more Azure resources.

High-level flow:
1. Parse POST payload as either `items[]` or a single-item object.
2. Enforce write safety: real updates require `dryRun=false` and `confirm=true`.
3. Merge target tag(s) into existing resource tags using ARM tags API.
4. Emit best-effort changelog entries and return per-item status (`preview`, `applied`, or `error`).

App settings used:

| App setting | Required | Used for |
|---|---|---|
| HTTP_TIMEOUT | Optional | Timeout for ARM tag read/write operations. |
| FABRIC_SQL_LOGGING_ENABLED | Optional | Enables best-effort changelog persistence. |
| FABRIC_SQL_SERVER | Optional | Fabric SQL endpoint for cc changelog writes. |
| FABRIC_SQL_DATABASE | Optional | Fabric SQL database for changelog writes. |
| FABRIC_SQL_DRIVER | Optional | ODBC driver used for SQL connection. |
| FABRIC_CHANGELOG_TABLE_CC | Optional | Target table for CC investigate action logs. |
| ARM_TENANT_B_TENANT_ID | Optional | Cross-tenant write profile support. |
| ARM_TENANT_B_CLIENT_ID | Optional | Cross-tenant service principal client ID. |
| ARM_TENANT_B_CLIENT_SECRET | Optional | Cross-tenant service principal secret. |
| ARM_TENANT_B_SUBSCRIPTIONS | Optional | Subscription routing list for cross-tenant operations. |

### azure_defender_compliance
Purpose:
- Calculates Defender posture progress for each Data Product ID using resource, pricing, assessment, and alert evidence.

High-level flow:
1. Parse and validate `dataProductIds`, `subscriptions`, and optional N/A overrides.
2. Discover tagged resources and determine defender-applicable resource types.
3. Query Defender pricing tiers (configured), assessments (running/health), and active high alerts.
4. Apply scoring rubric (`0/25/50/75/100`) and return per-ID rollups and diagnostics.

App settings used:

| App setting | Required | Used for |
|---|---|---|
| AZURE_SUBSCRIPTIONS | Optional | Default subscription list fallback. |
| RESOURCE_GRAPH_API_VERSION | Yes | API version used for Defender securityresources and resources queries. |
| HTTP_TIMEOUT | Optional | Timeout for Defender and ARG queries. |
| ARM_TENANT_B_TENANT_ID | Optional | Cross-tenant auth profile support. |
| ARM_TENANT_B_CLIENT_ID | Optional | Cross-tenant service principal client ID. |
| ARM_TENANT_B_CLIENT_SECRET | Optional | Cross-tenant service principal secret. |
| ARM_TENANT_B_SUBSCRIPTIONS | Optional | Subscription routing list for cross-tenant profile. |

### azure_residency_compliance_aws
Purpose:
- Lightweight connectivity/compliance helper for AWS S3 residency and tag retrieval.

High-level flow:
1. Accept bucket name (or ARN) plus optional AWS region hint.
2. Validate required AWS credential app settings.
3. Read bucket location and bucket tags via `boto3`.
4. Return normalized region/location and tag dictionary.

App settings used:

| App setting | Required | Used for |
|---|---|---|
| AWS_ACCESS_KEY_ID | Yes | AWS authentication for S3 API calls. |
| AWS_SECRET_ACCESS_KEY | Yes | AWS authentication secret for S3 API calls. |
| AWS_SESSION_TOKEN | Optional | Session token for temporary AWS credentials. |
| AWS_REGION | Optional | Default AWS region when request does not include region. |

## Sanitization notes
- Replaced organization-specific emails with example addresses.
- Replaced organization-specific sample bucket names.
- Replaced hard-coded sample data-product IDs with placeholder GUIDs.
- Kept environment-variable keys and generic cloud endpoints intact for learning/use-case clarity.