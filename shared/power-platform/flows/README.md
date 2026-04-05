# Power Platform Flows

This folder tracks the flows that integrate with the Purview custom connector and are intended to be invoked by Copilot (from a topic or as a tool).

## Invocation contract

Use this standard shape when invoking a flow from an agent Topic or Tool.

- Input envelope:
	- `requestId` (string, optional)
	- `caller` (string, optional)
	- `payload` (object, required)
- Output envelope:
	- `status` (string: `ok` or `error`)
	- `message` (string, optional)
	- `data` (object, optional)
	- `errors` (array, optional)

Each flow folder README defines flow-specific payload fields inside `payload`.

## Topic vs Tool decision matrix

<To Be Updated>

## Flow inventory

| Flow name | Short description | Flow details | Used by |
|---|---|---|---|
| FetchResidencyInfoFromPurview | Retrieves current Purview residency information for a data product. | [FetchResidencyInfoFromPurview/README.md](FetchResidencyInfoFromPurview/README.md) | |
| ResidencyUpdatePreview_wrapped | Generates a no-write preview of the planned residency update. | [ResidencyUpdatePreview_wrapped/README.md](ResidencyUpdatePreview_wrapped/README.md) | |
| ResidencyUpdateApply_wrapped | Applies a confirmed residency update and returns apply status. | [ResidencyUpdateApply_wrapped/README.md](ResidencyUpdateApply_wrapped/README.md) | |
| Apply_CCPII_Tag_And_Notify | Applies CC/PII investigate tag actions and triggers notification handling. | [Apply_CCPII_Tag_And_Notify/README.md](Apply_CCPII_Tag_And_Notify/README.md) | |
| Retrieve_CCPII_Eligibility | Retrieves CC/PII eligibility context for data products from Power BI-backed lookups. | [Retrieve_CCPII_Eligibility/README.md](Retrieve_CCPII_Eligibility/README.md) | |
| RetrieveSovDashboardInfo | Retrieves sovereignty dashboard summary metrics for agent responses. | [RetrieveSovDashboardInfo/README.md](RetrieveSovDashboardInfo/README.md) | |
| RunFabricPipeline | Invokes a Fabric pipeline endpoint and returns run status details. | [RunFabricPipeline/README.md](RunFabricPipeline/README.md) | |
