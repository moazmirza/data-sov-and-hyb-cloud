# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "05cc40d0-f1d9-4345-8dd5-f622b722340f",
# META       "default_lakehouse_name": "ext_lakehouse_fabric_moaz",
# META       "default_lakehouse_workspace_id": "66d5a770-33db-4274-a2fc-dad6a76b7c6f",
# META       "known_lakehouses": [
# META         {
# META           "id": "05cc40d0-f1d9-4345-8dd5-f622b722340f"
# META         }
# META       ]
# META     },
# META     "environment": {
# META       "environmentId": "033d0650-add4-471d-a1d7-66cdfaa42700",
# META       "workspaceId": "66d5a770-33db-4274-a2fc-dad6a76b7c6f"
# META     }
# META   }
# META }

# MARKDOWN ********************

# ## **Important Installs before executing anything**

# CELL ********************

# For Purview Assets API calls
# Run the pip command below only in non-pipeline executions: 
# %pip install msal

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## **Section: Building Delta Tables for Residency related Reporting**

# MARKDOWN ********************

# Microsoft Purview Self‑serve analytics publishes the governance metadata model into Microsoft Fabric OneLake so you can use Fabric compute (notebooks, pipelines, semantic model, Power BI) on it. [learn.microsoft.com], [Self-Serve...soft Learn | Learn.Microsoft.com]
# Your issue today is: the export files are updating, but your Lakehouse managed tables (dbo.uc_dataproduct, dbo.glossaryterm, dbo.glossarytermdataproductassignment) aren’t being refreshed automatically, so they remain stale.
# So automation = always re-materialize those dbo tables from the newest exported files (then rebuild Gold and refresh/reframe the semantic model if needed).

# MARKDOWN ********************

# Notebook parameters for products and glossary items for residency reporting

# CELL ********************


# Purview self serve parquet meta data gets imported under /Files
BASE_EXPORT_PATH = "Files/purview_meta_data/DomainModel"  

# Mapping: exported folder name -> dbo managed table name
TABLE_MAP = {
  "DataProduct": "uc_dataproduct",
  "GlossaryTerm": "glossaryterm",
  "GlossaryTermDataProductAssignment": "glossarytermdataproductassignment"
}


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Load Parquet → overwrite Delta managed table (dbo.*). This pattern (read files under /Files/..., write Delta into /Tables/managed tables) aligns with Fabric’s standard “Files → Delta table” approach

# CELL ********************


def overwrite_table_from_parquet(parquet_path, dbo_table):
    print(f"Loading parquet from: {parquet_path}")

    df = spark.read.format("parquet").load(parquet_path)
    print(f"{dbo_table}: rows loaded = {df.count()}")

    (
        df.write
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .format("delta")
        .saveAsTable(f"dbo.{dbo_table}")
    )

    print(f"✔ Overwrote managed Delta table dbo.{dbo_table}\n")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

for folder_name, dbo_table in TABLE_MAP.items():
    parquet_path = f"{BASE_EXPORT_PATH}/{folder_name}"   # adjust if nested
    overwrite_table_from_parquet(parquet_path, dbo_table)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Add “Gold refresh” inside the same notebook (so Power BI always reads curated)

# MARKDOWN ********************

# Old Code:
# %%sql
# DROP TABLE IF EXISTS dbo.dp_dataproductresidency_gold;
# 
# CREATE TABLE dbo.dp_dataproductresidency_gold
# USING DELTA
# AS
# WITH RegionTerms AS (
#   SELECT
#     GlossaryTermId,
#     GlossaryTermDisplayName AS ResidencyRegion
#   FROM glossaryterm
#   WHERE ParentGlossaryTermId = 'c8273dfa-93e9-4a6a-8358-fdb8152bc658'   -- Gl-Region parent
# ),
# ActiveRegionAssignments AS (
#   SELECT
#     DataProductId,
#     GlossaryTermId
#   FROM glossarytermdataproductassignment
#   WHERE ActiveFlag = 1
# )
# SELECT
#   dp.DataProductID,
#   dp.DataProductDisplayName,
#   dp.DataProductDescription,
#   rt.ResidencyRegion
# FROM uc_dataproduct dp
# LEFT JOIN ActiveRegionAssignments a
#   ON dp.DataProductID = a.DataProductId
# LEFT JOIN RegionTerms rt
#   ON a.GlossaryTermId = rt.GlossaryTermId;

# CELL ********************


%%sql
-- 1) Create the table once (schema-only). Safe to run every time.
CREATE TABLE IF NOT EXISTS dp_dataproductresidency_gold
(
  DataProductID STRING,
  DataProductDisplayName STRING,
  DataProductDescription STRING,
  ResidencyRegion STRING
)
USING DELTA;

-- 2) Overwrite contents each run WITHOUT dropping the table
INSERT OVERWRITE dp_dataproductresidency_gold
WITH RegionTerms AS (
  SELECT
    GlossaryTermId,
    GlossaryTermDisplayName AS ResidencyRegion
  FROM dbo.glossaryterm
  WHERE ParentGlossaryTermId = 'c8273dfa-93e9-4a6a-8358-fdb8152bc658'
),
ActiveRegionAssignments AS (
  SELECT
    DataProductId,
    GlossaryTermId
  FROM glossarytermdataproductassignment
  WHERE ActiveFlag = 1
)
SELECT
  dp.DataProductID,
  dp.DataProductDisplayName,
  dp.DataProductDescription,
  rt.ResidencyRegion
FROM dbo.uc_dataproduct dp
LEFT JOIN ActiveRegionAssignments a
  ON dp.DataProductID = a.DataProductId
LEFT JOIN RegionTerms rt
  ON a.GlossaryTermId = rt.GlossaryTermId;


# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Step 6 (Optional but recommended) — Create History table (trend over time)
# 
# 6A) Create Once
# 6B) Append snapshots after every Gold build
# 
# Now you can trend:
# 
# Coverage % over time
# Region changes over time
# New products added

# CELL ********************


%%sql


-- 1) Create history table ONCE (safe to run every time)
CREATE TABLE IF NOT EXISTS dp_dataproductresidency_history (
  SnapshotDate DATE,
  Snapshots TIMESTAMP,
  DataProductID STRING,
  DataProductDisplayName STRING,
  DataProductDescription STRING,
  ResidencyRegion STRING
)
USING DELTA;

-- 2) Append snapshot each run (explicit column list)
INSERT INTO dp_dataproductresidency_history
  (SnapshotDate, Snapshots, DataProductID, DataProductDisplayName, DataProductDescription, ResidencyRegion)
SELECT
  to_date(current_timestamp())  AS SnapshotDate,
  current_timestamp()           AS Snapshots,
  DataProductID,
  DataProductDisplayName,
  DataProductDescription,
  CAST(ResidencyRegion AS STRING) AS ResidencyRegion
FROM dp_dataproductresidency_gold;



# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## **Section: Building Delta Tables For Data Assets per data product reporting:**

# MARKDOWN ********************

# Parameters for products and product assets for assets/products reporting


# CELL ********************


# Base SSA export folder
BASE_EXPORT_PATH = "Files/purview_meta_data/DomainModel"

# Mapping for SSA raw ingestion (folder -> managed Delta table)
SSA_TABLE_MAP = {
    "DataAsset": "ssa_dataasset_raw",
    "DataProduct": "ssa_dataproduct_raw",
    "DataProductAssetAssignment": "ssa_dataproductassetassignment_raw",
    # Relationship optional for future lineage KPIs
    "Relationship": "ssa_relationship_raw"
}

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# INGEST SSA PARQUET → MANAGED DELTA (RAW TABLES)

# CELL ********************

for folder_name, dbo_table in SSA_TABLE_MAP.items():
    parquet_path = f"{BASE_EXPORT_PATH}/{folder_name}"
    overwrite_table_from_parquet(parquet_path, dbo_table)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# BUILD GOLD LAYER — DATA PRODUCT ASSET COUNTS (★ NEW ★)

# CELL ********************

# MAGIC %%sql
# MAGIC -- STEP A: Drop prior gold table (idempotent)
# MAGIC DROP TABLE IF EXISTS dp_dataproduct_assetcounts_gold;
# MAGIC 
# MAGIC -- STEP B: Create Gold table (materialized Delta)
# MAGIC CREATE TABLE dp_dataproduct_assetcounts_gold
# MAGIC USING DELTA AS
# MAGIC SELECT
# MAGIC     dp.DataProductDisplayName AS DataProductName,
# MAGIC     COUNT(da.DataAssetId) AS TotalAssets
# MAGIC FROM ssa_dataproduct_raw dp                -- Raw SSA Data Products
# MAGIC JOIN ssa_dataproductassetassignment_raw dpa -- Raw SSA DP→Asset mapping
# MAGIC     ON dp.DataProductId = dpa.DataProductId
# MAGIC JOIN ssa_dataasset_raw da                   -- Raw SSA Assets
# MAGIC     ON dpa.DataAssetId = da.DataAssetId
# MAGIC GROUP BY dp.DataProductDisplayName
# MAGIC ORDER BY TotalAssets DESC;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# APPEND HISTORY — ASSET COUNTS (★ NEW ★)

# CELL ********************


%%sql
-- Create history table if not exists
CREATE TABLE IF NOT EXISTS dp_dataproduct_assetcounts_history (
    SnapshotDate DATE,
    SnapshotTS TIMESTAMP,
    DataProductName STRING,
    TotalAssets INT
)
USING DELTA;

-- Append (preserves previous snapshots)
INSERT INTO dp_dataproduct_assetcounts_history
SELECT
    to_date(current_timestamp()) AS SnapshotDate,
    current_timestamp() AS SnapshotTS,
    DataProductName,
    TotalAssets
FROM dp_dataproduct_assetcounts_gold;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## **Section: Updated Purview level total Assets Count delta table update - Not parquet:**

# MARKDOWN ********************

# Step 1 — Create a tiny table in your Lakehouse

# CELL ********************

# MAGIC %%sql
# MAGIC CREATE TABLE IF NOT EXISTS dp_purviewassetcount_Current
# MAGIC (
# MAGIC     SnapshotUtc   TIMESTAMP,
# MAGIC     TotalAssets   BIGINT,
# MAGIC     IsApproximate BOOLEAN
# MAGIC )
# MAGIC USING DELTA;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Step 2 — Create a Service Principal for Purview APIs (one-time)
# 
# Purview-SAP-SP-Moaz
# 
# App/Client ID: 8c98bd9e-6f84-44a6-b663-7ae2aec7135d
# 
# Directory ID: 30c6fd04-b13e-43b1-906e-eed50b203685

# MARKDOWN ********************

# Retrieving KV secrets to be used throughout the notebook

# CELL ********************

# Azure Key Vault URL that contains the secret you want to read
kv_purview_sap_url = "https://kv-purview-sap.vault.azure.net/"

# Exact name of the secret stored inside that Key Vault
purview_sap_sp_moaz_kv_secret_name = "Secret-for-Purview-SAP-SP-Moaz"

# Read the secret value from Key Vault at runtime using Fabric notebook utilities
# This avoids hardcoding the secret directly in the notebook
purview_sap_sp_moaz_kv_secret_value = notebookutils.credentials.getSecret(
    kv_purview_sap_url,
    purview_sap_sp_moaz_kv_secret_name
)

# Exact name of the secret stored inside that Key Vault - spn-conf-comp-check-ext
spn_conf_comp_check_ext_secret_name = "Secret-for-spn-conf-comp-check-ext"

# Read the secret value from Key Vault at runtime using Fabric notebook utilities
# This avoids hardcoding the secret directly in the notebook
spn_conf_comp_check_ext_secret_value = notebookutils.credentials.getSecret(
    kv_purview_sap_url,
    spn_conf_comp_check_ext_secret_name
)

# Exact name of the secret stored inside that Key Vault - spn-conf-comp-check fdpo tenant
spn_conf_comp_check_secret_name = "Secret-for-spn-conf-comp-check"

# Read the secret value from Key Vault at runtime using Fabric notebook utilities
# This avoids hardcoding the secret directly in the notebook
spn_conf_comp_check_secret_value = notebookutils.credentials.getSecret(
    kv_purview_sap_url,
    spn_conf_comp_check_secret_name
)

# Simple confirmation message so you know the call succeeded
# Do not print the actual secret value
print("Secrets retrieved successfully")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Step 3 — Fabric Notebook that fetches the count and overwrites the 1-row table

# CELL ********************


import msal, requests
from datetime import datetime, timezone

# --- Fill these in ---
TENANT_ID = "30c6fd04-b13e-43b1-906e-eed50b203685"
CLIENT_ID = "8c98bd9e-6f84-44a6-b663-7ae2aec7135d"
CLIENT_SECRET = purview_sap_sp_moaz_kv_secret_value   # Better: read from Key Vault / secret store if you have one
PURVIEW_ACCOUNT = "ext-purview-moaz"  # the short name, used in the endpoint host
table_name = "dbo.dp_purviewassetcount_current"  # use your exact table


authority = f"https://login.microsoftonline.com/{TENANT_ID}"
app = msal.ConfidentialClientApplication(
    CLIENT_ID,
    authority=authority,
    client_credential=CLIENT_SECRET
)

token = app.acquire_token_for_client(scopes=["https://purview.azure.net/.default"])
if "access_token" not in token:
    raise Exception(f"Token acquisition failed: {token}")

access_token = token["access_token"]

url = f"https://{PURVIEW_ACCOUNT}.purview.azure.com/datamap/api/search/query?api-version=2023-09-01"

payload = {
    "keywords": "*",   # <-- changed from None
    "limit": 1
}

resp = requests.post(
    url,
    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    json=payload,
    timeout=60
)
resp.raise_for_status()
data = resp.json()

total = int(data.get("@search.count", 0))
approx = bool(data.get("@search.count.approximate", False))

snapshot = datetime.now(timezone.utc)

df = spark.createDataFrame(
    [(snapshot, total, approx)],
    "SnapshotUtc timestamp, TotalAssets long, IsApproximate boolean"
)

(df.write
  .format("delta")
  .mode("overwrite")
  .option("overwriteSchema", "true")
  .saveAsTable(table_name))

spark.sql(f"SELECT * FROM {table_name}").show(truncate=False)


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Step 4:  History table for Purview’s grand-total asset count so you can trend it over time in Power BI.

# CELL ********************

# MAGIC %%sql
# MAGIC 
# MAGIC -- 1) Create history table ONCE (safe to run every time)
# MAGIC CREATE TABLE IF NOT EXISTS dp_purviewassetcount_history (
# MAGIC   SnapshotDate   DATE,
# MAGIC   SnapshotUtc    TIMESTAMP,
# MAGIC   TotalAssets    BIGINT,
# MAGIC   IsApproximate  BOOLEAN
# MAGIC )
# MAGIC USING DELTA;
# MAGIC 
# MAGIC -- 2) Append snapshot each run (MERGE prevents duplicates if the pipeline reruns)
# MAGIC MERGE INTO dp_purviewassetcount_history AS h
# MAGIC USING (
# MAGIC   SELECT
# MAGIC     to_date(SnapshotUtc) AS SnapshotDate,
# MAGIC     SnapshotUtc,
# MAGIC     TotalAssets,
# MAGIC     IsApproximate
# MAGIC   FROM dp_purviewassetcount_current
# MAGIC ) AS c
# MAGIC ON h.SnapshotUtc = c.SnapshotUtc
# MAGIC WHEN NOT MATCHED THEN
# MAGIC   INSERT (SnapshotDate, SnapshotUtc, TotalAssets, IsApproximate)
# MAGIC   VALUES (c.SnapshotDate, c.SnapshotUtc, c.TotalAssets, c.IsApproximate);


# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## **Section: Create Drift-Ready Views for Anomaly Detection**

# MARKDOWN ********************

# These views convert raw history into ready-to-chart trend + delta tables.
# 
# A) Purview total assets deltas (spike/drop detector)
# 
# dp_purviewassetcount_deltas

# CELL ********************

# MAGIC %%sql
# MAGIC 
# MAGIC -- Create the deltas table once
# MAGIC CREATE TABLE IF NOT EXISTS dbo.dp_purviewassetcount_deltas (
# MAGIC   SnapshotUtc     TIMESTAMP,
# MAGIC   TotalAssets     BIGINT,
# MAGIC   IsApproximate   BOOLEAN,
# MAGIC   PrevTotalAssets BIGINT,
# MAGIC   DeltaAssets     BIGINT,
# MAGIC   DeltaPct        DOUBLE
# MAGIC )
# MAGIC USING DELTA;
# MAGIC 
# MAGIC -- Recompute deltas from history each run (simple + reliable)
# MAGIC INSERT OVERWRITE dbo.dp_purviewassetcount_deltas
# MAGIC WITH base AS (
# MAGIC   SELECT
# MAGIC     SnapshotUtc,
# MAGIC     TotalAssets,
# MAGIC     IsApproximate,
# MAGIC     LAG(TotalAssets) OVER (ORDER BY SnapshotUtc) AS PrevTotalAssets
# MAGIC   FROM dbo.dp_purviewassetcount_history
# MAGIC )
# MAGIC SELECT
# MAGIC   SnapshotUtc,
# MAGIC   TotalAssets,
# MAGIC   IsApproximate,
# MAGIC   PrevTotalAssets,
# MAGIC   (TotalAssets - PrevTotalAssets) AS DeltaAssets,
# MAGIC   CASE
# MAGIC     WHEN PrevTotalAssets IS NULL OR PrevTotalAssets = 0 THEN NULL
# MAGIC     ELSE (TotalAssets - PrevTotalAssets) * 1.0 / PrevTotalAssets
# MAGIC   END AS DeltaPct
# MAGIC FROM base;
# MAGIC 
# MAGIC -- Optional sanity check
# MAGIC SELECT *
# MAGIC FROM dbo.dp_purviewassetcount_deltas
# MAGIC ORDER BY SnapshotUtc DESC
# MAGIC LIMIT 10;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# B) Product asset deltas table (spike/drop per data product) dbo.dp_dataproduct_assetcount_deltas

# CELL ********************

# MAGIC %%sql
# MAGIC 
# MAGIC CREATE TABLE IF NOT EXISTS dbo.dp_dataproduct_assetcount_deltas (
# MAGIC   SnapshotTS    TIMESTAMP,
# MAGIC   SnapshotDate  DATE,
# MAGIC   DataProductName STRING,
# MAGIC   TotalAssets   BIGINT,
# MAGIC   PrevAssets    BIGINT,
# MAGIC   DeltaAssets   BIGINT,
# MAGIC   DeltaPct      DOUBLE
# MAGIC )
# MAGIC USING DELTA;
# MAGIC 
# MAGIC INSERT OVERWRITE dbo.dp_dataproduct_assetcount_deltas
# MAGIC WITH base AS (
# MAGIC   SELECT
# MAGIC     SnapshotTS,
# MAGIC     SnapshotDate,
# MAGIC     DataProductName,
# MAGIC     CAST(TotalAssets AS BIGINT) AS TotalAssets,
# MAGIC     LAG(CAST(TotalAssets AS BIGINT)) OVER (PARTITION BY DataProductName ORDER BY SnapshotTS) AS PrevAssets
# MAGIC   FROM dbo.dp_dataproduct_assetcounts_history
# MAGIC )
# MAGIC SELECT
# MAGIC   SnapshotTS,
# MAGIC   SnapshotDate,
# MAGIC   DataProductName,
# MAGIC   TotalAssets,
# MAGIC   PrevAssets,
# MAGIC   (TotalAssets - PrevAssets) AS DeltaAssets,
# MAGIC   CASE
# MAGIC     WHEN PrevAssets IS NULL OR PrevAssets = 0 THEN NULL
# MAGIC     ELSE (TotalAssets - PrevAssets) * 1.0 / PrevAssets
# MAGIC   END AS DeltaPct
# MAGIC FROM base;
# MAGIC 
# MAGIC -- sanity check
# MAGIC SELECT *
# MAGIC FROM dbo.dp_dataproduct_assetcount_deltas
# MAGIC ORDER BY SnapshotTS DESC, ABS(DeltaAssets) DESC
# MAGIC LIMIT 20;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# C) Residency changes table (the “compliance drift” detector) dp_dataproduct_residency_deltas

# CELL ********************

# MAGIC %%sql
# MAGIC 
# MAGIC -- Create the new "deltas" table
# MAGIC CREATE TABLE IF NOT EXISTS dbo.dp_dataproduct_residency_deltas (
# MAGIC   SnapshotUtc           TIMESTAMP,
# MAGIC   SnapshotDate          DATE,
# MAGIC   DataProductID         STRING,
# MAGIC   DataProductDisplayName STRING,
# MAGIC   PrevSnapshotUtc       TIMESTAMP,
# MAGIC   PrevResidencyRegion   STRING,
# MAGIC   ResidencyRegion       STRING,
# MAGIC   HasChanged            BOOLEAN
# MAGIC )
# MAGIC USING DELTA;
# MAGIC 
# MAGIC -- Recompute from history each run
# MAGIC INSERT OVERWRITE dbo.dp_dataproduct_residency_deltas
# MAGIC WITH base AS (
# MAGIC   SELECT
# MAGIC     Snapshots AS SnapshotUtc,
# MAGIC     SnapshotDate,
# MAGIC     DataProductID,
# MAGIC     DataProductDisplayName,
# MAGIC     CAST(ResidencyRegion AS STRING) AS ResidencyRegion,
# MAGIC     LAG(CAST(ResidencyRegion AS STRING)) OVER (PARTITION BY DataProductID ORDER BY Snapshots) AS PrevResidencyRegion,
# MAGIC     LAG(Snapshots) OVER (PARTITION BY DataProductID ORDER BY Snapshots) AS PrevSnapshotUtc
# MAGIC   FROM dbo.dp_dataproductresidency_history
# MAGIC )
# MAGIC SELECT
# MAGIC   SnapshotUtc,
# MAGIC   SnapshotDate,
# MAGIC   DataProductID,
# MAGIC   DataProductDisplayName,
# MAGIC   PrevSnapshotUtc,
# MAGIC   PrevResidencyRegion,
# MAGIC   ResidencyRegion,
# MAGIC   CASE
# MAGIC     WHEN PrevResidencyRegion IS NULL THEN FALSE
# MAGIC     WHEN ResidencyRegion IS NULL THEN FALSE
# MAGIC     WHEN ResidencyRegion <> PrevResidencyRegion THEN TRUE
# MAGIC     ELSE FALSE
# MAGIC   END AS HasChanged
# MAGIC FROM base;
# MAGIC 
# MAGIC -- sanity check: show only changes
# MAGIC SELECT *
# MAGIC FROM dbo.dp_dataproduct_residency_deltas
# MAGIC WHERE HasChanged = TRUE
# MAGIC ORDER BY SnapshotUtc DESC
# MAGIC LIMIT 50;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# D) One KPI trend table for anomaly monitoring (easy Power BI visuals)
# 
# This creates a single timeline table you can use for 4–6 line charts + anomaly detection + alerts. dbo.dp_sovereignty_kpis_timeline_table

# CELL ********************

# MAGIC %%sql
# MAGIC 
# MAGIC CREATE TABLE IF NOT EXISTS dbo.dp_sovereignty_kpis_timeline_table (
# MAGIC   SnapshotUtc TIMESTAMP,
# MAGIC   TotalPurviewAssets BIGINT,
# MAGIC   IsApproximate BOOLEAN,
# MAGIC   TotalProductAssets BIGINT,
# MAGIC   TotalDataProducts BIGINT,
# MAGIC   ProductsMissingResidency BIGINT,
# MAGIC   ProductsWithResidency BIGINT,
# MAGIC   ResidencyCoveragePct DOUBLE,
# MAGIC   ProductAssetsToPurviewAssetsRatio DOUBLE
# MAGIC )
# MAGIC USING DELTA;
# MAGIC 
# MAGIC -- Lookback window in seconds.
# MAGIC -- Set this to match your pipeline schedule + some buffer.
# MAGIC -- If your pipeline runs every 30 min, 7200 (2 hours) is safe.
# MAGIC -- If it runs every 6 hours, use 21600 (6 hours) or 28800 (8 hours).
# MAGIC WITH
# MAGIC purview AS (
# MAGIC   SELECT
# MAGIC     SnapshotUtc,
# MAGIC     CAST(TotalAssets AS BIGINT) AS TotalPurviewAssets,
# MAGIC     CAST(IsApproximate AS BOOLEAN) AS IsApproximate
# MAGIC   FROM dbo.dp_purviewassetcount_history
# MAGIC ),
# MAGIC 
# MAGIC product_assets_agg AS (
# MAGIC   SELECT
# MAGIC     SnapshotTS AS SnapUtc,
# MAGIC     CAST(SUM(CAST(TotalAssets AS BIGINT)) AS BIGINT) AS TotalProductAssets
# MAGIC   FROM dbo.dp_dataproduct_assetcounts_history
# MAGIC   GROUP BY SnapshotTS
# MAGIC ),
# MAGIC 
# MAGIC residency_agg AS (
# MAGIC   SELECT
# MAGIC     Snapshots AS SnapUtc,
# MAGIC     CAST(COUNT(DISTINCT DataProductID) AS BIGINT) AS TotalDataProducts,
# MAGIC     CAST(SUM(CASE WHEN ResidencyRegion IS NULL OR ResidencyRegion = '' THEN 1 ELSE 0 END) AS BIGINT) AS ProductsMissingResidency,
# MAGIC     CAST(SUM(CASE WHEN ResidencyRegion IS NOT NULL AND ResidencyRegion <> '' THEN 1 ELSE 0 END) AS BIGINT) AS ProductsWithResidency
# MAGIC   FROM dbo.dp_dataproductresidency_history
# MAGIC   GROUP BY Snapshots
# MAGIC ),
# MAGIC 
# MAGIC -- AS-OF match: pick latest product_assets snapshot <= purview snapshot
# MAGIC product_assets_asof AS (
# MAGIC   SELECT
# MAGIC     p.SnapshotUtc AS BaseSnapshotUtc,
# MAGIC     pa.TotalProductAssets,
# MAGIC     ROW_NUMBER() OVER (
# MAGIC       PARTITION BY p.SnapshotUtc
# MAGIC       ORDER BY pa.SnapUtc DESC
# MAGIC     ) AS rn
# MAGIC   FROM purview p
# MAGIC   LEFT JOIN product_assets_agg pa
# MAGIC     ON pa.SnapUtc <= p.SnapshotUtc
# MAGIC    AND (unix_timestamp(p.SnapshotUtc) - unix_timestamp(pa.SnapUtc)) <= 21600
# MAGIC ),
# MAGIC 
# MAGIC -- AS-OF match: pick latest residency snapshot <= purview snapshot
# MAGIC residency_asof AS (
# MAGIC   SELECT
# MAGIC     p.SnapshotUtc AS BaseSnapshotUtc,
# MAGIC     r.TotalDataProducts,
# MAGIC     r.ProductsMissingResidency,
# MAGIC     r.ProductsWithResidency,
# MAGIC     ROW_NUMBER() OVER (
# MAGIC       PARTITION BY p.SnapshotUtc
# MAGIC       ORDER BY r.SnapUtc DESC
# MAGIC     ) AS rn
# MAGIC   FROM purview p
# MAGIC   LEFT JOIN residency_agg r
# MAGIC     ON r.SnapUtc <= p.SnapshotUtc
# MAGIC    AND (unix_timestamp(p.SnapshotUtc) - unix_timestamp(r.SnapUtc)) <= 21600
# MAGIC )
# MAGIC 
# MAGIC INSERT OVERWRITE dbo.dp_sovereignty_kpis_timeline_table
# MAGIC SELECT
# MAGIC   p.SnapshotUtc,
# MAGIC   p.TotalPurviewAssets,
# MAGIC   p.IsApproximate,
# MAGIC   pa.TotalProductAssets,
# MAGIC   r.TotalDataProducts,
# MAGIC   r.ProductsMissingResidency,
# MAGIC   r.ProductsWithResidency,
# MAGIC   CASE
# MAGIC     WHEN r.TotalDataProducts IS NULL OR r.TotalDataProducts = 0 THEN NULL
# MAGIC     ELSE r.ProductsWithResidency * 1.0 / r.TotalDataProducts
# MAGIC   END AS ResidencyCoveragePct,
# MAGIC   CASE
# MAGIC     WHEN p.TotalPurviewAssets IS NULL OR p.TotalPurviewAssets = 0 THEN NULL
# MAGIC     ELSE pa.TotalProductAssets * 1.0 / p.TotalPurviewAssets
# MAGIC   END AS ProductAssetsToPurviewAssetsRatio
# MAGIC FROM purview p
# MAGIC LEFT JOIN (SELECT BaseSnapshotUtc, TotalProductAssets FROM product_assets_asof WHERE rn = 1) pa
# MAGIC   ON pa.BaseSnapshotUtc = p.SnapshotUtc
# MAGIC LEFT JOIN (SELECT BaseSnapshotUtc, TotalDataProducts, ProductsMissingResidency, ProductsWithResidency FROM residency_asof WHERE rn = 1) r
# MAGIC   ON r.BaseSnapshotUtc = p.SnapshotUtc
# MAGIC -- Option B: keep only fully-populated KPI rows (prevents partial NULL rows in the timeline)
# MAGIC WHERE pa.TotalProductAssets IS NOT NULL
# MAGIC   AND r.TotalDataProducts IS NOT NULL
# MAGIC ORDER BY p.SnapshotUtc;
# MAGIC 
# MAGIC -- sanity check
# MAGIC SELECT *
# MAGIC FROM dbo.dp_sovereignty_kpis_timeline_table
# MAGIC ORDER BY SnapshotUtc DESC
# MAGIC LIMIT 20;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## **Section: Building Tables for Personal Info and Conf. Computing Conformance**

# MARKDOWN ********************

# Create the missing raw tables (Fabric Notebook – PySpark)
# 
# In your Lakehouse “Files” area, locate the SSA export folders for dataAssetColumn and classification (names may vary slightly).
# Then plug those OneLake paths below.
# 
# - dbo.ssa_dataassetcolumn_raw
# - dbo.ssa_classification_raw

# CELL ********************

# --- Register SSA DomainModel Delta folders as Lakehouse tables ---

# These folders contain Delta tables (they include a _delta_log folder),
# so we must use format("delta") rather than read.parquet().
path_dataassetcolumn = "Files/purview_meta_data/DomainModel/DataAssetColumn"
path_classification  = "Files/purview_meta_data/DomainModel/Classification"

# 0) (Optional) sanity check: list files and confirm _delta_log exists
# from notebookutils import mssparkutils
# display(mssparkutils.fs.ls(path_dataassetcolumn))

# 1) Read DataAssetColumn as DELTA (NOT parquet)
df_cols = spark.read.format("delta").load(path_dataassetcolumn)

# 2) Persist it as a managed Lakehouse table for easier SQL querying
#    (This writes a new Delta table managed by the Lakehouse metastore.)
df_cols.write.format("delta").mode("overwrite").saveAsTable("dbo.ssa_dataassetcolumn_raw")

# 3) Read Classification as DELTA (NOT parquet)
df_cls = spark.read.format("delta").load(path_classification)

# 4) Persist it as a managed Lakehouse table
df_cls.write.format("delta").mode("overwrite").saveAsTable("dbo.ssa_classification_raw")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Verify the two new tables exist and inspect their schemas

# CELL ********************

# Verify the tables were created and readable (first 5 rows each)

df_cols = spark.table("dbo.ssa_dataassetcolumn_raw")
df_cls  = spark.table("dbo.ssa_classification_raw")

print("ssa_dataassetcolumn_raw rows:", df_cols.count())
print("ssa_classification_raw rows:", df_cls.count())

display(df_cols.limit(5))
display(df_cls.limit(5))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Print schemas so we can reference the correct column names in SQL (no guessing)

print("=== Schema: dbo.ssa_dataassetcolumn_raw ===")
df_cols.printSchema()

print("=== Schema: dbo.ssa_classification_raw ===")
df_cls.printSchema()

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Register DataAssetColumnClassificationAssignment as a Lakehouse table (commented)
# 
# dbo.ssa_dataassetcolumnclassificationassignment_raw

# CELL ********************

# ---------------------------------------------
# Load DomainModel/DataAssetColumnClassificationAssignment (Delta) into a Lakehouse table
# ---------------------------------------------

# 1) Point to the DomainModel folder (this folder contains a Delta table)
path_col_class = "Files/purview_meta_data/DomainModel/DataAssetColumnClassificationAssignment"

# 2) Read it as Delta (DO NOT use parquet, because the folder contains _delta_log)
df_map = spark.read.format("delta").load(path_col_class)

# 3) (Optional) sanity check: view schema + a few rows
df_map.printSchema()
display(df_map.limit(10))

# 4) Save as a managed Lakehouse table for SQL usage
df_map.write.format("delta").mode("overwrite").saveAsTable("dbo.ssa_dataassetcolumnclassificationassignment_raw")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Write the DP-level table dp_dataproduct_fullnameclassification_current using the real column names from your environment

# CELL ********************

# MAGIC %%sql
# MAGIC -- dp_dataproduct_fullnameclassification_current
# MAGIC -- Purpose:
# MAGIC --   One row per Data Product showing whether ANY of its assigned asset columns
# MAGIC --   are classified as MICROSOFT.PERSONAL.NAME (Full Name).
# MAGIC --
# MAGIC -- Inputs:
# MAGIC --   dbo.uc_dataproduct
# MAGIC --     - provides the base DP list and display name (DataProductId, DataProductDisplayName)
# MAGIC --   dbo.ssa_dataproductassetassignment_raw
# MAGIC --     - maps DataProductId -> DataAssetId
# MAGIC --   dbo.ssa_dataassetcolumn_raw
# MAGIC --     - maps DataAssetId -> ColumnId (columns of each asset)
# MAGIC --   dbo.ssa_dataassetcolumnclassificationassignment_raw
# MAGIC --     - maps (DataAssetId, ColumnId) -> ClassificationId
# MAGIC --   dbo.ssa_classification_raw
# MAGIC --     - maps ClassificationId -> ClassificationDisplayName
# MAGIC --
# MAGIC -- Output:
# MAGIC --   SnapshotUtc               : when the table was produced
# MAGIC --   DataProductId             : DP id (this is the key you’ll join to Azure tag later)
# MAGIC --   DataProductDisplayName    : friendly DP name (for readability in Power BI / debugging)
# MAGIC --   HasFullNameClassification : 1 if DP has any Full Name classified column, else 0
# MAGIC --   FullNameColumnCount       : count of distinct columns matching Full Name (debug/useful metric)
# MAGIC 
# MAGIC CREATE OR REPLACE TABLE dbo.dp_dataproduct_fullnameclassification_current AS
# MAGIC WITH
# MAGIC -- 1) Base list of Data Products (ensures every DP appears even if it has 0 matches)
# MAGIC --    Pull display name here so we can carry it into the final output.
# MAGIC dp AS (
# MAGIC   SELECT DISTINCT
# MAGIC     DataProductId,
# MAGIC     DataProductDisplayName
# MAGIC   FROM dbo.uc_dataproduct
# MAGIC ),
# MAGIC 
# MAGIC -- 2) Data Product -> Data Asset assignments (SSA)
# MAGIC -- NOTE: If this table uses different column casing/names, adjust here only.
# MAGIC dp_asset AS (
# MAGIC   SELECT DISTINCT
# MAGIC     DataProductId,
# MAGIC     DataAssetId
# MAGIC   FROM dbo.ssa_dataproductassetassignment_raw
# MAGIC ),
# MAGIC 
# MAGIC -- 3) Expand assigned assets into their columns (SSA DataAssetColumn)
# MAGIC dp_columns AS (
# MAGIC   SELECT
# MAGIC     da.DataProductId,
# MAGIC     col.DataAssetId,
# MAGIC     col.ColumnId
# MAGIC   FROM dp_asset da
# MAGIC   JOIN dbo.ssa_dataassetcolumn_raw col
# MAGIC     ON da.DataAssetId = col.DataAssetId
# MAGIC ),
# MAGIC 
# MAGIC -- 4) Keep only those DP columns that are classified as Full Name
# MAGIC dp_fullname_cols AS (
# MAGIC   SELECT
# MAGIC     dc.DataProductId,
# MAGIC 
# MAGIC     -- Count DISTINCT ColumnId to avoid double-counting if assignment rows repeat
# MAGIC     COUNT(DISTINCT dc.ColumnId) AS FullNameColumnCount
# MAGIC   FROM dp_columns dc
# MAGIC 
# MAGIC   -- Join to the column->classification assignment mapping table
# MAGIC   JOIN dbo.ssa_dataassetcolumnclassificationassignment_raw map
# MAGIC     ON dc.DataAssetId = map.DataAssetId
# MAGIC    AND dc.ColumnId   = map.ColumnId
# MAGIC 
# MAGIC   -- Join to classification lookup for the display name
# MAGIC   JOIN dbo.ssa_classification_raw cls
# MAGIC     ON map.ClassificationId = cls.ClassificationId
# MAGIC 
# MAGIC   -- Filter to your target classification
# MAGIC   WHERE cls.ClassificationDisplayName = 'MICROSOFT.PERSONAL.NAME'
# MAGIC 
# MAGIC   GROUP BY dc.DataProductId
# MAGIC )
# MAGIC 
# MAGIC -- 5) Final output: left join so every DP shows up with a 0/1 flag
# MAGIC SELECT
# MAGIC   current_timestamp() AS SnapshotUtc,                          -- snapshot timestamp (consistent with *_current)
# MAGIC   dp.DataProductId,
# MAGIC   dp.DataProductDisplayName,
# MAGIC 
# MAGIC   -- 1 if we found at least one matching column
# MAGIC   CASE WHEN f.DataProductId IS NULL THEN 0 ELSE 1 END
# MAGIC     AS HasFullNameClassification,
# MAGIC 
# MAGIC   -- Supporting metric (how many columns triggered the flag)
# MAGIC   COALESCE(f.FullNameColumnCount, 0) AS FullNameColumnCount
# MAGIC FROM dp
# MAGIC LEFT JOIN dp_fullname_cols f
# MAGIC   ON dp.DataProductId = f.DataProductId;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# New table storing Conf Computing check for the product id:
# dbo.dp_compute_inventory_current

# CELL ********************

# ------------------------------------------------------------
# dp_compute_inventory_current
# Purpose:
#   Cross-tenant ARG pull of VMs tagged with dataproductid
#   and compute confidential status from VM properties (NOT tags).
#
# Tag used:
#   - dataproductid (join key)
#
# Confidential logic:
#   - properties.securityProfile.securityType == 'ConfidentialVM' => IsConfidential = 1
# ------------------------------------------------------------

# Already built in the environment when running from the pipeline:
# import requests, msal


from functools import reduce
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType

# 1) Define each tenant context (SPN + subscriptions in that tenant)
TENANT_CONTEXTS = [
    {
        "tenant_id": "30c6fd04-b13e-43b1-906e-eed50b203685",
        "client_id": "a99598e5-cd1e-49bf-a3d4-a6ab04f23b12",
        "client_secret": spn_conf_comp_check_ext_secret_value,
        "subscriptions": ["17d52165-9be5-418b-a7f4-6b3e7d82d155"]
    },
    {
        "tenant_id": "16b3c013-d300-468d-ac64-7eda0820b6d3",
        "client_id": "789e24ac-10c1-41c4-bea6-73e5728cce00",
        "client_secret": spn_conf_comp_check_secret_value,
        "subscriptions": ["3557eaf8-74a8-4e8a-b260-b28c90fc9379"]
    }
]


query = r"""
Resources
| where type =~ 'Microsoft.Compute/virtualMachines'
| extend DataProductId = tolower(tostring(tags['dataproductid']))
| where isnotempty(DataProductId)
| extend SecurityType = tostring(properties.securityProfile.securityType)
| extend IsConfidential = iif(tolower(SecurityType) == 'confidentialvm', 1, 0)
| project
    SnapshotUtc = now(),
    DataProductId,
    ComputeResourceId = id,
    ComputeName = name,
    ResourceGroup = resourceGroup,
    SubscriptionId = subscriptionId,
    Location = location,
    SecurityType,
    IsConfidential
"""

url = "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2024-04-01"

# Explicit schema so empty results don't break, and IsConfidential is int (1/0)
schema = StructType([
    StructField("SnapshotUtc", StringType(), True),
    StructField("DataProductId", StringType(), True),
    StructField("ComputeResourceId", StringType(), True),
    StructField("ComputeName", StringType(), True),
    StructField("ResourceGroup", StringType(), True),
    StructField("SubscriptionId", StringType(), True),
    StructField("Location", StringType(), True),
    StructField("SecurityType", StringType(), True),
    StructField("IsConfidential", IntegerType(), True),
])

dfs = []

for ctx in TENANT_CONTEXTS:
    authority = f"https://login.microsoftonline.com/{ctx['tenant_id']}"
    app = msal.ConfidentialClientApplication(
        ctx["client_id"], authority=authority, client_credential=ctx["client_secret"]
    )

    tok = app.acquire_token_for_client(scopes=["https://management.azure.com/.default"])
    if "access_token" not in tok:
        raise Exception(f"Token acquisition failed for tenant {ctx['tenant_id']}: {tok}")
    token = tok["access_token"]

    payload = {"subscriptions": ctx["subscriptions"], "query": query}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    res = requests.post(url, json=payload, headers=headers)
    res.raise_for_status()

    rows = res.json().get("data", [])
    print(f"Tenant {ctx['tenant_id']} subs {ctx['subscriptions']} -> rows: {len(rows)}")

    df = spark.createDataFrame(rows, schema=schema)

    # Add TenantId for traceability
    df = df.withColumn("TenantId", F.lit(ctx["tenant_id"]))

    # Optional: boolean convenience column for Power BI / SQL
    df = df.withColumn("IsConfidentialBool", (F.col("IsConfidential") == F.lit(1)))

    dfs.append(df)

final_df = reduce(lambda a, b: a.unionByName(b, allowMissingColumns=True), dfs)

(final_df.write.format("delta")
  .mode("overwrite")
  .saveAsTable("dbo.dp_compute_inventory_current"))

display(final_df.limit(50))


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Because it separates “non-compliant” from “unknown mapping”:
# 
# Full Name + mapped compute + NOT confidential (true gap) dp_dataproduct_fullname_not_confidential_current
# 
# Full Name + NO mapped compute (coverage gap / tagging gap) dbo.dp_dataproduct_fullname_no_compute_mapping_current

# CELL ********************

# MAGIC %%sql
# MAGIC -- ============================================================
# MAGIC -- TABLE 1: Full Name DPs that are mapped to compute, but NONE of the mapped VMs are Confidential
# MAGIC -- Purpose:
# MAGIC --   This is the "true compliance gap" tile:
# MAGIC --   - DP has Full Name classification (sensitive)
# MAGIC --   - DP is mapped to at least 1 VM via dataproductid tag
# MAGIC --   - But the mapped compute is NOT confidential (per ARG securityProfile.securityType)
# MAGIC -- Output:
# MAGIC --   dbo.dp_dataproduct_fullname_not_confidential_current
# MAGIC -- ============================================================
# MAGIC 
# MAGIC CREATE OR REPLACE TABLE dbo.dp_dataproduct_fullname_not_confidential_current AS
# MAGIC WITH dp AS (
# MAGIC   -- Normalize DataProductId for consistent joins (case-insensitive)
# MAGIC   SELECT
# MAGIC     lower(DataProductId) AS DataProductId,
# MAGIC     DataProductDisplayName,
# MAGIC     HasFullNameClassification,
# MAGIC     FullNameColumnCount
# MAGIC   FROM dbo.dp_dataproduct_fullnameclassification_current
# MAGIC ),
# MAGIC cc AS (
# MAGIC   -- Roll up VM-level compute inventory to DP-level
# MAGIC   SELECT
# MAGIC     lower(DataProductId) AS DataProductId,
# MAGIC     COUNT(*) AS ComputeVmCount,
# MAGIC     MAX(IsConfidential) AS AnyConfidential   -- 1 if ANY mapped VM is confidential
# MAGIC   FROM dbo.dp_compute_inventory_current
# MAGIC   GROUP BY lower(DataProductId)
# MAGIC )
# MAGIC SELECT
# MAGIC   current_timestamp() AS SnapshotUtc,        -- snapshot time for this derived table
# MAGIC   dp.DataProductId,
# MAGIC   dp.DataProductDisplayName,
# MAGIC   dp.FullNameColumnCount,
# MAGIC   cc.ComputeVmCount,
# MAGIC   cc.AnyConfidential AS IsConfidentialCompute
# MAGIC FROM dp
# MAGIC JOIN cc
# MAGIC   ON dp.DataProductId = cc.DataProductId     -- only DPs that actually have compute mapping
# MAGIC WHERE
# MAGIC   dp.HasFullNameClassification = 1           -- DP has Full Name classification
# MAGIC   AND cc.ComputeVmCount > 0                  -- must have mapped compute
# MAGIC   AND cc.AnyConfidential = 0;                -- NONE of the mapped compute is confidential


# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# MAGIC %%sql
# MAGIC -- ============================================================
# MAGIC -- TABLE 2: Full Name DPs that have NO mapped compute at all
# MAGIC -- Purpose:
# MAGIC --   This is the "coverage / mapping gap" tile:
# MAGIC --   - DP has Full Name classification (sensitive)
# MAGIC --   - But we cannot evaluate compute posture because there are 0 VMs tagged with dataproductid
# MAGIC -- Output:
# MAGIC --   dbo.dp_dataproduct_fullname_no_compute_mapping_current
# MAGIC -- ============================================================
# MAGIC 
# MAGIC CREATE OR REPLACE TABLE dbo.dp_dataproduct_fullname_no_compute_mapping_current AS
# MAGIC WITH dp AS (
# MAGIC   -- Normalize DataProductId for consistent joins (case-insensitive)
# MAGIC   SELECT
# MAGIC     lower(DataProductId) AS DataProductId,
# MAGIC     DataProductDisplayName,
# MAGIC     HasFullNameClassification,
# MAGIC     FullNameColumnCount
# MAGIC   FROM dbo.dp_dataproduct_fullnameclassification_current
# MAGIC ),
# MAGIC cc AS (
# MAGIC   -- DP-level count of mapped VMs (via dataproductid tag)
# MAGIC   SELECT
# MAGIC     lower(DataProductId) AS DataProductId,
# MAGIC     COUNT(*) AS ComputeVmCount
# MAGIC   FROM dbo.dp_compute_inventory_current
# MAGIC   GROUP BY lower(DataProductId)
# MAGIC )
# MAGIC SELECT
# MAGIC   current_timestamp() AS SnapshotUtc,        -- snapshot time for this derived table
# MAGIC   dp.DataProductId,
# MAGIC   dp.DataProductDisplayName,
# MAGIC   dp.FullNameColumnCount,
# MAGIC   COALESCE(cc.ComputeVmCount, 0) AS ComputeVmCount
# MAGIC FROM dp
# MAGIC LEFT JOIN cc
# MAGIC   ON dp.DataProductId = cc.DataProductId
# MAGIC WHERE
# MAGIC   dp.HasFullNameClassification = 1           -- DP has Full Name classification
# MAGIC   AND COALESCE(cc.ComputeVmCount, 0) = 0;    -- zero compute mapping => coverage gap

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ## **Next, Use this notebook in the pipeline to automate refresh**
