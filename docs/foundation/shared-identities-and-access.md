# Shared Identities And Access

Use least-privilege identities and separate read, orchestration, and remediation permissions where possible.

## Shared Expectations

- Managed identity for function workloads
- Service-to-service access documented per module
- Role assignments reviewed before enabling action flows
- Environment-specific values stored outside source control

Each action-enabled module should document extra permissions in its own `prepare.md` and `dependencies.md`.
