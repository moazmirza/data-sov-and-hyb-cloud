# Fabric Repro Import Order And Rebind Runbook

Purpose: provide a repeatable import order and dependency rebinding flow for this selected-item pack in another tenant/workspace.

## Preconditions
- Target Fabric workspace exists and user has required permissions.
- Required capacities and gateway/network dependencies are ready in target environment.
- Parameters in `workspace.parameters.template.json` are populated for target environment.
- Sanitized pack has been rebuilt and validated.

## Import Order
1. `<FABRIC_LAKEHOUSE_NAME>__Lakehouse` (Lakehouse)
2. `semantic_model_purview_dataproduct_residency_gold__SemanticModel` (SemanticModel)
3. `Compliance Scoring Model__SemanticModel` (SemanticModel)
4. `Refresh And Automate Purview parquet to gold__Notebook` (Notebook)
5. `notebook_fabric_function_sov_compliance_checks_new__Notebook` (Notebook)
6. `pipe_refresh_sov_checks_and_reporting_contoso__DataPipeline` (DataPipeline)
7. `report_purview_dataproduct_residency__Report` (Report)
8. `Compliance Scoring Report for Data Agent__Report` (Report)
9. `Sov Data Agent Contoso__DataAgent` (DataAgent)

## Metadata-Only Items
- `<FABRIC_LAKEHOUSE_NAME>__SQLEndpoint` (SQLEndpoint)
- `Sovereignty_Alerts_Activator__Reflex` (Reflex)

These two were metadata-only from the export API in this run. Recreate manually in target workspace, then bind to corresponding imported artifacts.

## Rebind Checklist
1. Lakehouse
- Verify shortcut and external location references.
- Replace any placeholder host values with target values.

2. Semantic Models
- Update data source endpoints and workspace-scoped IDs.
- Confirm model refresh succeeds.

3. Notebooks
- Replace placeholders in tenant/subscription/client settings.
- Configure Key Vault and secret names in target environment.
- Run notebook cells for smoke validation.

4. Data Pipeline
- Rebind notebook references to newly imported notebook IDs.
- Rebind connection and destination references.
- Validate schedule and trigger behavior.

5. Reports
- Rebind each report to target semantic models.
- Verify page visuals and measure rendering.

6. Data Agent
- Rebind artifact and workspace references in draft and published configs.
- Validate runtime behavior and prompt flows.

7. Metadata-only resources
- Recreate SQL Endpoint and Reflex resources manually.
- Link them to imported lakehouse/workspace resources.

## Validation Sequence
1. Run semantic model refresh.
2. Run notebook smoke tests.
3. Run pipeline dry run and then full run.
4. Open reports and validate visuals.
5. Validate Data Agent interaction.

## Notes
- Keep source artifacts unchanged.
- Share only sanitized artifacts for cross-tenant onboarding.
