# Solution Module 3: Dashboard Hydration for CC-for-PII

## Solution Module 3 Details: Dashboard Hydration for CC-for-PII

### Scope

This solution documents how Confidential Compute for PII (CC-for-PII) is hydrated from notebook processing into the `Compliance Dashboard` page visuals.

### Architecture Diagram

```mermaid
flowchart LR
	LH["Lakehouse sources"] --> BASE["Notebook: build dp_base"]
	LH --> RULES["Ruleset table<br/>CC_SKUS_TABLE = rs_confidential_compute_skus"]
	BASE --> PII{"PII gate<br/>HasFullNameClassification == 1 ?"}
	PII -- No --> NA1["NA_NotPII<br/>CCForPIIScore = 100"]
	PII -- Yes --> CALL["Call Azure Function<br/>/api/azure/ccForPiiCompliance<br/>payload: subscriptions + dataProductIds"]

	CALL --> ARG["Azure Function lookup in ARG<br/>match by tags['dataproductid']"]
	ARG --> RT{"Resource type"}
	RT --> VM["Azure VM<br/>vmSize/securityType<br/>ARG first, ARM fallback"]
	RT --> ARC["Arc machine<br/>detectedProperties.model"]
	RT --> SQLVM["SQL VM<br/>resolve linked compute VM<br/>ARG first, ARM fallback"]
	RT --> NONE["No matching tagged resource"]

	VM --> RET["Return resourceFound, vmApplicable,<br/>ccLookupSku, ccLookupSkuSource,<br/>resource metadata + patch fields"]
	ARC --> RET
	SQLVM --> RET
	NONE --> RET

	RET --> JOIN["Notebook joins API output<br/>back to full product list"]
	NA1 --> JOIN

	JOIN --> SCORE["Notebook scoring rubric<br/>0 / 25 / 50 / 75 / 100"]
	RULES --> SCORE
	SCORE --> CC["Write dp_dataproduct_cccompliance_current"]
	CC --> SUMM["Build compliance summary<br/>CCScorePct = AVG(CCForPIIScore)<br/>by DataProductId"]
	SUMM --> MODEL["Semantic model mapping<br/>Conf. Compute Compliance (%) <- CCScorePct"]
	MODEL --> DASH["Compliance Dashboard visuals<br/>Gauge + table"]
```

### Data Product Applicability (PII gate)

The notebook confirms PII applicability from table `dp_dataproduct_fullnameclassification_current` and uses these fields:
- `HasFullNameClassification`
- `FullNameColumnCount`

It then derives:
- `CCApplicable = (HasFullNameClassification == 1)`

Ruleset lookup used by notebook scoring:
- `CC_SKUS_TABLE = "rs_confidential_compute_skus"`
- This table is joined by normalized lookup SKU/model (`LookupSku_lc`) to determine:
	- `IsConfidentialSku`
	- `IsApprovedSkuCalc`

Behavior:
- `CCApplicable = true`: data product is sent to the CC endpoint for evaluation.
- `CCApplicable = false`: data product is still retained in output as `NA_NotPII` with score `100`.

### Azure Function lookup key

The Azure Function performs Resource Graph lookup using the Azure resource tag key:
- `tags['dataproductid']`

It matches resources against the incoming `dataProductIds` and applies supported-type logic for:
- Azure VM
- Arc machine
- SQL VM (using linked compute VM)

### CC Scoring Rubric (clarified)

| Outcome | Exact condition | Score | Meaning |
|---|---|---:|---|
| `NA_NotPII` | `CCApplicable == false` | 100 | Out of CC scope because product is not PII-applicable |
| `NotFound` | `resourceFound == false` | 0 | No matching tagged Azure resource found |
| `NA_NotApplicable` | `resourceFound == true` and `vmApplicable == false` | 100 | Resource exists but not in supported CC compute scope |
| Applicable, Azure VM lookup missing | `resourceFound == true` and `vmApplicable == true` and Azure VM lookup SKU missing | 25 | In-scope Azure VM but VM size lookup unavailable |
| Applicable, Arc model missing | `resourceFound == true` and `vmApplicable == true` and Arc lookup model missing | 50 | In-scope Arc resource but model unavailable |
| Applicable, non-confidential SKU/model | `IsConfidentialSku == false` | 50 | Resource is in scope but not running confidential compute |
| Applicable, confidential but unapproved | `IsConfidentialSku == true` and `IsApprovedSkuCalc == false` | 75 | Confidential compute detected but not approved |
| Applicable, confidential and approved | `IsConfidentialSku == true` and `IsApprovedSkuCalc == true` | 100 | Fully compliant confidential compute posture |

How the ruleset affects scoring:
- If lookup SKU/model does not exist in `rs_confidential_compute_skus`, notebook treats it as non-confidential (`IsConfidentialSku = false`) and scores `50` when applicable.
- If it exists with approved flag false, notebook scores `75`.
- If it exists with approved flag true, notebook scores `100`.

### Dashboard roll-up mapping

- Per-product score is written as `CCForPIIScore` in `dp_dataproduct_cccompliance_current`.
- Compliance summary derives `CCScorePct = AVG(CCForPIIScore)` per `DataProductId`.
- Semantic model maps `CCScorePct` to `Conf. Compute Compliance (%)`.
- Compliance Dashboard gauge and table visuals render from that mapped score.