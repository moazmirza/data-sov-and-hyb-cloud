# func-purv-contoso Sanitized Export

This folder contains a sanitized export of the Azure Functions app source retrieved from admin VFS.

## Included files
- function_app.py
- host.json
- requirements.txt

## Functions discovered
### purview_residency
Purpose:
- Resolves the current Purview residency term for a given data product name.

High-level flow:
1. Accept `dataProductName` (required) and optional `parentTermName` from query or JSON body.
2. Resolve the data product and linked residency glossary term in Purview.
3. If a residency term is missing, return a structured "missing residency" response.
4. Normalize the residency value and return a consistent JSON payload.

### purview_residency_update_preview
Purpose:
- Produces a safe, non-writing preview plan before any Purview residency change.

High-level flow:
1. Parse request payload (data product ID, target residency code, expected current residency, metadata).
2. Validate request shape and prerequisites (target term lookup, current state checks).
3. Build a plan showing what relationships would be removed/added.
4. Return preview details and status code without mutating Purview.

### purview_residency_update_apply
Purpose:
- Applies the Purview residency update plan with explicit confirmation controls.

High-level flow:
1. Parse request and enforce safe defaults (`dryRun=true` unless explicitly disabled).
2. Require explicit confirmation (`confirm=true`) for real writes.
3. Remove old residency relationship(s) and create the new relationship when applicable.
4. Emit action-log/changelog metadata (best effort) and return final status + details.

### azure_tag_compliance
Purpose:
- Evaluates tag-based compliance per Data Product ID across Azure resources.

High-level flow:
1. Parse and validate `dataProductIds` and `subscriptions`.
2. Query Azure Resource Graph for resources tagged with matching `dataproductid`.
3. Read observed tag signals (`resource-origin`, `sovereignty-zone`).
4. Score each Data Product ID and return matched/missing breakdowns.

### azure_residency_compliance
Purpose:
- Returns all resource locations for each Data Product ID so downstream systems can score residency.

High-level flow:
1. Parse and validate `dataProductIds` and `subscriptions`.
2. Query Resource Graph for tag matches using common `DataProductId` tag variants.
3. Group resources by Data Product ID and derive distinct location codes.
4. Return per-ID resource lists, location sets, and missing IDs.

### azure_cc_for_pii_compliance
Purpose:
- Collects Confidential Compute and patch-assessment signals for VM-like assets tied to each Data Product ID.

High-level flow:
1. Parse and validate `dataProductIds` and `subscriptions`.
2. Query Resource Graph for tagged resources and prioritize VM/Arc/SQL VM resource types.
3. Derive CC lookup SKU from ARG first, with ARM fallback for missing VM details.
4. Pull patch assessment summaries from Update Manager ARG tables.
5. Return per-ID compliance evidence (resource kind, lookup SKU source, patch status, details).

### azure_cc_pii_investigate_tag_apply
Purpose:
- Applies (or previews) an investigate/compliance tag update to one or more Azure resources.

High-level flow:
1. Parse POST payload as either `items[]` or a single-item object.
2. Enforce write safety: real updates require `dryRun=false` and `confirm=true`.
3. Merge target tag(s) into existing resource tags using ARM tags API.
4. Emit best-effort changelog entries and return per-item status (`preview`, `applied`, or `error`).

### azure_defender_compliance
Purpose:
- Calculates Defender posture progress for each Data Product ID using resource, pricing, assessment, and alert evidence.

High-level flow:
1. Parse and validate `dataProductIds`, `subscriptions`, and optional N/A overrides.
2. Discover tagged resources and determine defender-applicable resource types.
3. Query Defender pricing tiers (configured), assessments (running/health), and active high alerts.
4. Apply scoring rubric (`0/25/50/75/100`) and return per-ID rollups and diagnostics.

### azure_residency_compliance_aws
Purpose:
- Lightweight connectivity/compliance helper for AWS S3 residency and tag retrieval.

High-level flow:
1. Accept bucket name (or ARN) plus optional AWS region hint.
2. Validate required AWS credential app settings.
3. Read bucket location and bucket tags via `boto3`.
4. Return normalized region/location and tag dictionary.

## Sanitization notes
- Replaced organization-specific emails with example addresses.
- Replaced organization-specific sample bucket names.
- Replaced hard-coded sample data-product IDs with placeholder GUIDs.
- Kept environment-variable keys and generic cloud endpoints intact for learning/use-case clarity.