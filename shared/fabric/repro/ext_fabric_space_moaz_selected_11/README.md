# Fabric Repro Pack - Selected 11 Items

Purpose: reusable local artifact pack for the 11 selected Fabric items from workspace `ext_fabric_space_moaz`, sanitized for cross-tenant onboarding.

## What is included
- `manifest.selected-items.json`: item name/type/id mapping for the selected scope.
- `export-summary.json`: per-item export status from Fabric API.
- `import-order-and-rebind-runbook.md`: deterministic import order and post-import rebinding checklist.
- Per-item folders:
  - `item-metadata.json`
  - `definition/` files when Fabric `getDefinition` returned parts.
  - `definition-response.json` or `export-error.txt`.
- `security-review-notebooks.md`: notebook secret scan results.
- `sanitized/`: shareable copies with IDs/URLs/emails replaced by placeholders.
- `workspace.parameters.template.json`: target-environment values to populate.
- `_automation/sanitize-pack.ps1`: rebuilds sanitized tree with stronger replacement rules.
- `_automation/validate-sanitized-pack.ps1`: validates no forbidden source literals remain.
- `_automation/sanitization-report.json`: generated replacement report.
- `_automation/sanitization-validation-report.json`: generated validation results.

## Export result snapshot
- Exported with definition parts: Semantic models, reports, lakehouse, data pipeline, notebooks, data agent.
- Metadata only: `SQLEndpoint` and `Reflex` (Fabric API returned 400 for `getDefinition` on these item types in this workspace).

## Notebook security review
- Current result in `security-review-notebooks.md`: no hardcoded secret/password patterns detected by heuristic regex scan.
- Note: this is static pattern scanning; keep manual review for credential helper usage and indirect secret loading.

## Reproduction approach for another tenant
1. Create a target Fabric workspace and required capacities.
2. Populate `workspace.parameters.template.json` with your tenant/workspace/resource IDs.
3. Rebuild sanitized artifacts:
  - `pwsh ./_automation/sanitize-pack.ps1`
4. Validate sanitized artifacts:
  - `pwsh ./_automation/validate-sanitized-pack.ps1`
5. Import item definitions from `sanitized/` following `import-order-and-rebind-runbook.md`.
6. Rebind lakehouse/pipeline/report/semantic model dependencies to target resources.
7. Run notebook validation and refresh pipeline dependencies.

## Notes
- This pack was intentionally created locally only (not pushed to `dev`).
- `sanitized/` replaces known workspace/tenant/subscription/client IDs, key endpoints, and email values with placeholders.
