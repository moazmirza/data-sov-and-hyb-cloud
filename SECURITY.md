# Security Policy

## Supported Versions

This repository is a reference implementation. The latest `main` branch is the supported baseline.

## Reporting a Vulnerability

Do not open public issues for security concerns.

Report vulnerabilities privately to: `security@contoso.example`

Include:
- Summary and impact
- Reproduction steps
- Affected files or docs
- Suggested mitigation

## Sensitive Data Rules

Never commit secrets, keys, tokens, tenant identifiers, or customer-specific exports.
Use placeholders from `shared/templates/base/`.
