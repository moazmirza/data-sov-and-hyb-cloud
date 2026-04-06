# Notebook Secret Review

Scope: exported notebook-related files from selected Fabric items.

Result: no hardcoded secret/password values were found in exported notebook code.

Observed patterns to keep sanitized for reusable publishing:
- Secret retrieval is done through Key Vault (`notebookutils.credentials.getSecret(...)`) rather than inline secret literals.
- Secret names are hardcoded (for example `Secret-for-spn-conf-comp-check`) and should be treated as sensitive metadata.
- Environment-specific values are hardcoded in notebook code (tenant IDs, client IDs, subscription IDs, Key Vault URL, Function App URL).

Manual spot-check notes:
- `notebook_fabric_function_sov_compliance_checks_new` pulls secret values from Key Vault and does not print them.
- `Refresh And Automate Purview parquet to gold` also pulls secret values from Key Vault and references them in auth payloads.
- No plaintext password assignments were found.

Notes: this is a heuristic scan. Manual review is still recommended.
