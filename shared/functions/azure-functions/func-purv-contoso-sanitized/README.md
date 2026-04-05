# func-purv-contoso Sanitized Export

This folder contains a sanitized export of the Azure Functions app source retrieved from admin VFS.

## Included files
- function_app.sanitized.py
- host.sanitized.json
- requirements.sanitized.txt

## Functions discovered
- azure_cc_for_pii_compliance
- azure_cc_pii_investigate_tag_apply
- azure_defender_compliance
- azure_residency_compliance
- azure_residency_compliance_aws
- azure_tag_compliance
- purview_residency
- purview_residency_update_apply
- purview_residency_update_preview

## Sanitization notes
- Replaced organization-specific emails with example addresses.
- Replaced organization-specific sample bucket names.
- Replaced hard-coded sample data-product IDs with placeholder GUIDs.
- Kept environment-variable keys and generic cloud endpoints intact for learning/use-case clarity.