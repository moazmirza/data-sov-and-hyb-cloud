# Notebook Execution Blocks & Data Transformations

This section documents each notebook's structure and data transformation flow.

## Notebook 1: "Refresh And Automate Purview parquet to gold__Notebook"

**Purpose:** Materializes Purview SSA exports into Delta tables, builds gold-layer aggregations, populates history/delta tables for trend analysis and anomaly detection.

### Block Flow:

1. **Dependencies** → Install msal for Purview API
2. **Raw Ingest** → Parquet → dbo.* managed tables (uc_dataproduct, glossaryterm, ssa_dataasset_raw, etc.)
3. **Gold: Residency** → 3-table JOIN → dp_dataproductresidency_gold (1 row per product + region)
4. **History: Residency** → Append gold snapshots → dp_dataproductresidency_history
5. **Gold: Assets** → Aggregate join → dp_dataproduct_assetcounts_gold (asset counts per product)
6. **History: Assets** → Append gold snapshots → dp_dataproduct_assetcounts_history
7. **Purview API** → Fetch total asset count from Purview → dp_purviewassetcount_current
8. **History: Purview** → Append snapshots → dp_purviewassetcount_history
9. **Delta Tables** → LAG window functions on history → dp_*_deltas (compute percent-change for anomalies)
10. **KPI Timeline** → AS-OF joins (time-bounded) → dp_sovereignty_kpis_timeline_table (single unified timeline)

### Component Flow Diagram:

```
Files (OneLake) 
    ↓
Parquet Ingest 
    ↓ 
dbo.* (Raw/DBL Layer)
    ├─→ uc_dataproduct
    ├─→ glossaryterm
    ├─→ ssa_dataasset_raw
    └─→ ssa_classification_raw
    ↓
Gold Tables (Curated DW)
    ├─→ dp_dataproductresidency_gold (product + region)
    └─→ dp_dataproduct_assetcounts_gold (product + asset count)
    ↓
History Layer (Append-Only)
    ├─→ dp_dataproductresidency_history
    ├─→ dp_dataproduct_assetcounts_history
    └─→ dp_purviewassetcount_history (from Purview API)
    ↓
Delta/Anomaly Layer
    ├─→ dp_purviewassetcount_deltas (LAG: prev-vs-current)
    ├─→ dp_dataproduct_assetcount_deltas
    └─→ dp_dataproduct_residency_deltas
    ↓
KPI Timeline (Report Ready)
    ↓
    └─→ dp_sovereignty_kpis_timeline_table → Power BI
```

---

## Notebook 2: "notebook_fabric_function_sov_compliance_checks_new__Notebook"

**Purpose:** Call Azure Functions to score data products against governance rulesets; persist compliance scorecards (current + history) for multi-dimensional Power BI reporting.

### Block Flow:

1. **Setup + Config** → Import libraries, retrieve KV secrets, define function routes/subscriptions
2. **Helpers** → Register auth/batching/Delta-write utilities (reusable across compliance checks)
3. **Load DP Base** → Read dp_dataproductresidency_gold + derive product categories
4. **Applicability Flags** → Mark which checks apply per product:
   - **TagApplicable**: ¬IsS3 (S3 external, skip tagging)
   - **ResidencyApplicable**: All products
   - **CCApplicable**: PII-bearing products only (HasFullNameClassification=1)
   - **DefenderApplicable**: VMs, SQL, Storage, Arc; ¬S3, ¬Fabric
5. **Tag Compliance** → POST batch DP IDs → Tag API → Reshape responses → ScoreDF
6. **Write Tag** → Overwrite current + append history
7. **Residency Compliance** → POST all DPs → Residency API → Reshape → ScoreDF
8. **Write Residency** → Overwrite current + append history
9. **CC for PII Compliance** → POST (CC-applicable only) → CC API → ScoreDF (N/A=100 for excluded)
10. **Write CC** → Overwrite current + append history
11. **Defender Compliance** → POST (compute/SQL/Arc) → Defender API → ScoreDF (N/A for excluded)
12. **Write Defender** → Overwrite current + append history
13. **Compliance Summary** (optional) → UNION/PIVOT all scorecards → 1 row per product, N compliance columns

### Component Transformation Flow:

```
dp_dataproductresidency_gold + PII classification table
    ↓
Load + Categorize
    (IsS3, IsVmLike, IsSqlPaaS, IsHybridComputeMachine, HasFullNameClassification)
    ↓
Derive Applicability Flags
    ├─ TagApplicable        (¬S3)
    ├─ ResidencyApplicable  (all)
    ├─ CCApplicable         (PII-bearing)
    └─ DefenderApplicable   (compute/SQL/Arc)
    ↓
Batch Calls to 4 Azure Functions
    ├─ /api/azure/tagCompliance
    ├─ /api/azure/residencyCompliance
    ├─ /api/azure/ccForPiiCompliance
    └─ /api/azure/defenderCompliance
    ↓
Reshape API Responses
    (HTTP 200 → JSON results → Spark DataFrame)
    ↓
4 Scorecard Tables (Current + History)
    ├─ dp_dataproduct_tagcompliance_current/history
    ├─ dp_dataproduct_residencycompliance_current/history
    ├─ dp_dataproduct_cccompliance_current/history
    └─ dp_dataproduct_defendercompliance_current/history
    ↓
Optional: Compliance Summary
    └─ dp_dataproduct_compliance_summary_current 
       (1 row/product, columns: TagScore, ResidencyScore, CCScore, DefenderScore, *)
    ↓
    └─→ Power BI Compliance Matrix & Multi-Dimensional Scorecard
```

---

## Data Transformation Reference Table

| Notebook | Block | Input | Transformation | Output | Key Purpose |
|----------|-------|-------|-----------------|--------|------------|
| 1 | 2 | Parquet (wide) | Spark read + overwrite mode | Delta table (managed) | Materialize raw SSA exports |
| 1 | 3 | 3 tables (products, glossary, assignments) | LEFT JOIN chain | 1 DP row + residency region | Curate gold-layer residency |
| 1 | 4 | Gold table | SELECT + ADD SnapshotDate/timestamp | Snapshot row | Build history tape |
| 1 | 9 | History tables | window LAG + arithmetic | Delta/pct columns | Compute anomalies |
| 1 | 10 | Multiple histories | AS-OF time joins + denorm | 1 unified timeline row | Report-ready KPI table |
| 2 | 4 | 1 base table + text heur | WHEN THEN logic (regex) + LEFT JOIN | Enriched DP frame w/ flags | Categorize products & mark applicability |
| 2 | 5-12 | Enriched DP frame + subs | **Batch POST to Function** → parse JSON | Scored DF (per dimension) | Score each compliance dimension |
| 2 | 13 | 4 scored tables | UNION/PIVOT/denormalize | 1 row/product, N cols | Multi-dimensional scorecard |

---

## Key Takeaways

- **Notebook 1**: ETL pipeline (source → ingestion → gold → history → delta → KPI)
- **Notebook 2**: ELT + scoring (load → enrich → batch API calls → scorecard storage)
- **Applicability Logic**: N/A products score 100 on excluded dimensions (auto-pass)
- **History Tables**: Append-only design enables trend analysis, anomaly detection, and compliance audits
- **Power BI Consumer**: Reads current tables (latest state) and deltas/timeline for trending
