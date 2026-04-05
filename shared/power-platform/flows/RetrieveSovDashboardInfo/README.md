# RetrieveSovDashboardInfo

## Purpose
Retrieves sovereignty dashboard metrics from Power BI-backed data and returns summarized dashboard fields for agent consumption.

## Trigger
- Trigger name: manual
- Trigger type: Request

## Action sequence
1. Respond_to_the_agent
2. pbiProductMissingResidencyCount
3. composeProductMissingResidencyCount
4. composeProductMissingResidencyName
5. composeTotalProductsCount
6. composeTotalDataProductAssets
7. composeAssetsByDataProduct
8. composeEligibleResidencyUpdateCount
9. composeEligibleResidencyUpdateProducts
10. composeEligibleResidencyUpdateDetails
11. composeBlockedUnapprovedRegionCount
12. composeBlockedUnapprovedRegionProducts

## Connector dependencies
- shared_powerbi (Power BI connector)

## Expected invocation pattern
- Typical caller: Copilot via Topic or Tool
- Typical input: optional dashboard filter context
- Typical output: dashboard counts and grouped summary details

## Notes
- This flow aggregates read-only metrics and is suitable for dashboard-style agent responses.
