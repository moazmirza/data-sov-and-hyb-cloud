# Solution Module 5: CC-for-PII Compliance via Agent

## Prerequisite

- Module 1 must be completed.
- Module 3 must be completed because this module depends on CC score and investigation outputs.

## Architecture Diagram

```mermaid
flowchart LR
    M3[Module 3 investigate output table] --> INV[dp_dataproduct_cccompliance_investigate_current in semantic model]
    INV --> TOPIC[Copilot topic ApplyPIICCInvestigateTag]

    TOPIC --> FLOW1[Flow Retrieve_CCPII_Eligibility]
    FLOW1 --> PBI[Power BI dataset query for product match and eligibility]
    PBI --> TOPIC

    TOPIC --> FLOW2[Flow Apply_CCPII_Tag_And_Notify]
    FLOW2 --> API[/api/azure/ccPiiInvestigateTagApply via CCPII_ApplyInvestigateTag]
    API --> TAG[Resource tag merge action]
    API --> TEAM[Teams adaptive card notification]
    API --> LOG[Action response and changelog signal]
    LOG --> TOPIC
    TOPIC --> USER[Final confirmation to user]
```

## Building Blocks

| Component | Artifact | Role |
|---|---|---|
| Copilot topic | `Default_contosoDataSovereigntyAssistant.topic.ApplyPIICCInvestigateTag` | User conversation and guarded action orchestration |
| Eligibility flow | `Retrieve_CCPII_Eligibility-50BE9EDC-8162-76A3-8EC8-BB961BA97E10.json` | Resolves product and checks single eligible investigation candidate |
| Apply flow | `Apply_CCPII_Tag_And_Notify-A30252E4-DC13-F111-8341-002248081FAF.json` | Executes tag action and posts Teams card |
| Custom connector operation | `CCPII_ApplyInvestigateTag` | Calls function backend for governed tag application |
| Function endpoint | `/api/azure/ccPiiInvestigateTagApply` | Performs tag apply/skip/fail processing and response details |
| Investigation table | `dp_dataproduct_cccompliance_investigate_current` | Source of actionable candidates (`CCScorePct` 50/75 and PII-scoped rows) |

## Testing

1. Validate exact-match scenario returns one eligible row and enables confirmation path.
2. Validate non-unique or no-match product input blocks apply and returns guidance message.
3. Validate eligible candidate with `CCScorePct` 50 or 75 triggers apply flow with expected payload fields.
4. Validate Teams adaptive card posts with resource id, owner email, score, tag key/value, and request id.
5. Validate result payload correctly reflects `applied/skipped/failed` counts from function response.

## Comments

- Mapped to slide 30 in the PPT mapping you provided.
- Current exported eligibility flow contains a hard-coded `S/4` search string in one query path and should be treated as a known refinement item.