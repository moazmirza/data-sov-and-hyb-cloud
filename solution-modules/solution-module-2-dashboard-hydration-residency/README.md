# Solution Module 2: Dashboard Hydration for Residency

## Prerequisite

- Module 1 must be completed.
- `dataproductid` tagging and policy baseline from Module 1 must be in place.
- Purview and Fabric baseline setup from Module 1 must be available.

## Architecture Diagram

```mermaid
flowchart LR
    GOLD[Gold table dp_dataproductresidency_gold] --> NB[Fabric notebook compliance checks]
    RULES[rs_approved_regions] --> NB
    NB --> API[/api/azure/residencyCompliance]
    API --> ARG[Azure Resource Graph by dataproductid tag]
    API --> AWS[/api/azure/residencyComplianceAws fallback for S3]
    ARG --> NB
    AWS --> NB
    NB --> CURR[dp_dataproduct_residencycompliance_current]
    CURR --> SUMM[dp_dataproduct_compliance_summary_current]
    SUMM --> SEM[Semantic model]
    SEM --> PBI[Compliance Dashboard residency visuals]
```

## Building Blocks

| Component | Artifact | Role |
|---|---|---|
| Notebook | `notebook_fabric_function_sov_compliance_checks_new (5).ipynb` | Orchestrates residency scoring and writes current-state tables |
| Function API | `/api/azure/residencyCompliance` | Resolves Azure resource location signal using ARG and `dataproductid` tags |
| Function API fallback | `/api/azure/residencyComplianceAws` | Provides location fallback for S3-backed products when Azure resource is absent |
| Gold source table | `dp_dataproductresidency_gold` | Baseline data product and glossary residency input |
| Rules table | `rs_approved_regions` | Approved residency policy reference for scoring |
| Output table | `dp_dataproduct_residencycompliance_current` | Product-level residency compliance output |
| Reporting table | `dp_dataproduct_compliance_summary_current` | Aggregated score for dashboard consumption |

## Testing

1. Run notebook residency block and verify `dp_dataproduct_residencycompliance_current` refreshes.
2. Validate score outputs for expected paths: `NotFound`, `MissingGlossaryResidency`, `ApprovedButMismatched`, `Compliant`.
3. Validate at least one S3 fallback case exercises `/api/azure/residencyComplianceAws`.
4. Validate dashboard visuals reflect updated `ResidencyScorePct` values.
5. Validate approved-region blocking behavior when region is outside `rs_approved_regions`.

## Comments

- Mapped to slide 27 in the PPT mapping you provided.
- Module 4 consumes the residency outputs and eligibility state from this module.