# Policy Definitions

Store sanitized policy definition JSON files in this folder.

For each definition, document:
- Purpose
- Scope
- Parameters
- Effect
- Dependencies
- Output used by downstream scoring

## Example Policy Matrix

| Policy | Purpose | Effect | Scope | Used by downstream component |
|---|---|---:|---|---|
| Residency Policy | Restrict or audit region placement | Audit/Deny | Subscription or RG | Fabric scoring |
| Tagging Policy | Require `dataproductid` and `sovereignty-zone` | Audit/Modify | Subscription | Tag compliance report |
