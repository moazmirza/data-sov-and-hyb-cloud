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
# META     }
# META   }
# META }

# MARKDOWN ********************

# ### Imports

# CELL ********************

import os, json, time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
import msal

from pyspark.sql import functions as F
from pyspark.sql import types as T

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ### Retrieving KV Secrets


# CELL ********************

# Azure Key Vault URL that contains the secret you want to read
kv_purview_sap_url = "https://kv-purview-sap.vault.azure.net/"

# Exact name of the secret stored inside that Key Vault
spn_func_compliance_check_secret_name = "Secret-for-spn-func-compliance-check"

# Read the secret value from Key Vault at runtime using Fabric notebook utilities
# This avoids hardcoding the secret directly in the notebook
spn_func_compliance_check_secret_value = notebookutils.credentials.getSecret(
    kv_purview_sap_url,
    spn_func_compliance_check_secret_name
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

# ### Config

# CELL ********************

# =========================
# Core inputs (base DP list)
# =========================
DP_BASE_TABLE = "dp_dataproductresidency_gold"  # must contain DataProductID, DataProductDisplayName, DataProductDescription, ResidencyRegion

# Enrichment / ruleset tables
APPROVED_REGIONS_TABLE = "rs_approved_regions"            # expects region_name, region_code, approved, notes
CC_SKUS_TABLE = "rs_confidential_compute_skus"            # expects sku, is_approved (or similar)
PII_CLASS_TABLE = "dp_dataproduct_fullnameclassification_current"  # expects DataProductId, HasFullNameClassification, FullNameColumnCount

# =========================
# Output tables (your naming)
# =========================
TAG_CURRENT, TAG_HISTORY = "dp_dataproduct_tagcompliance_current", "dp_dataproduct_tagcompliance_history"
RES_CURRENT, RES_HISTORY = "dp_dataproduct_residencycompliance_current", "dp_dataproduct_residencycompliance_history"
CC_CURRENT,  CC_HISTORY  = "dp_dataproduct_cccompliance_current",  "dp_dataproduct_cccompliance_history"
DEF_CURRENT, DEF_HISTORY = "dp_dataproduct_defendercompliance_current", "dp_dataproduct_defendercompliance_history"

# =========================
# Function App + routes
# =========================
FUNCTION_BASE_URL = "https://func-purv-contoso-gkcbavefesdqhre2.eastus2-01.azurewebsites.net"  # <-- set once

ROUTES = {
    "tag":       "/api/azure/tagCompliance",
    "residency": "/api/azure/residencyCompliance",
    "cc":        "/api/azure/ccForPiiCompliance",
    "defender":  "/api/azure/defenderCompliance",
}

# =========================
# Subscriptions + batching
# =========================
SUBSCRIPTIONS = ["<SUBSCRIPTION_ID_1>","<SUBSCRIPTION_ID_2>"]   # same list you used for tag/cc/residency
BATCH_SIZE = int(os.getenv("DP_CHUNK_SIZE", "200"))  # function supports up to 500; 200 is safe

# =========================
# EasyAuth (Entra) token (same as your existing notebook)
# =========================
TENANT_ID = "30c6fd04-b13e-43b1-906e-eed50b203685"
CLIENT_ID = "05d107b2-6b35-48e5-93fe-824663d5fb8e"
CLIENT_SECRET = spn_func_compliance_check_secret_value

RESOURCE_APP_CLIENT_ID = "fec2dea8-4aa7-4903-bab4-7139a09b9056"  # the App ID URI audience used by EasyAuth
SCOPE = [f"api://{RESOURCE_APP_CLIENT_ID}/.default"]  # MSAL expects list[str]

if not FUNCTION_BASE_URL.startswith("http"):
    raise ValueError("Set FUNCTION_BASE_URL like: https://<your-functionapp>.azurewebsites.net")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ### Shared Helpers

# CELL ********************

# =========================================
# HELPERS (Auth + API batching + Delta writes)
# =========================================

from typing import Any, Dict, List, Optional
import json
import time
import requests
import msal

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


# -----------------------------
# Auth / API helpers
# -----------------------------
def get_access_token() -> str:
    authority = f"https://login.microsoftonline.com/{TENANT_ID}"
    app = msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        authority=authority,
        client_credential=CLIENT_SECRET
    )
    result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        raise RuntimeError(f"Token error: {json.dumps(result)[:1500]}")
    return result["access_token"]


def chunks(lst: List[str], n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


def post_batched(
    route: str,
    dp_ids: List[str],
    extra_payload: Optional[Dict[str, Any]] = None,
    retries: int = 3,
    sleep_s: float = 0.05
) -> List[Dict[str, Any]]:
    """
    Calls your Azure Function route for dataProductIds in batches and returns a concatenated
    list of the function's 'results' arrays.

    Expected function response shape:
      { "results": [ ... ] }
    """
    url = FUNCTION_BASE_URL.rstrip("/") + route
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    all_results: List[Dict[str, Any]] = []

    for batch in chunks(dp_ids, BATCH_SIZE):
        payload: Dict[str, Any] = {"subscriptions": SUBSCRIPTIONS, "dataProductIds": batch}
        if extra_payload:
            payload.update(extra_payload)

        last_err: Optional[Exception] = None
        success = False

        for attempt in range(1, retries + 1):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=120)

                if r.status_code == 401:
                    # Refresh token once (rare but can happen in long notebook runs)
                    token = get_access_token()
                    headers["Authorization"] = f"Bearer {token}"
                    r = requests.post(url, headers=headers, json=payload, timeout=120)

                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:1500]}")

                j = r.json()
                all_results.extend(j.get("results", []) or [])
                success = True
                break

            except Exception as e:
                last_err = e
                if attempt < retries:
                    time.sleep(2 * attempt)  # simple backoff

        if not success:
            raise RuntimeError(f"Failed calling {url}: {str(last_err)[:1500]}")

        time.sleep(sleep_s)

    return all_results


# -----------------------------
# Delta write helpers (strict names + target-type conform for history append)
# -----------------------------
def write_delta_overwrite(df: DataFrame, table_name: str):
    (df.write.format("delta")
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(table_name))


def _conform_df_to_table_schema(df: DataFrame, table_name: str) -> DataFrame:
    """
    Conform df to an existing Delta table schema:
      - align column casing to target table
      - cast overlapping columns to target types
      - add missing target columns as null (typed)
      - select columns in exact target order
    This is especially useful for HISTORY append to avoid DELTA_FAILED_TO_MERGE_FIELDS.
    """
    if not spark.catalog.tableExists(table_name):
        return df

    target = spark.table(table_name)
    target_schema = target.schema
    target_cols = [f.name for f in target_schema.fields]
    target_cols_by_lower = {c.lower(): c for c in target_cols}

    # 1) Align casing of incoming cols to target (case-insensitive)
    incoming_cols = df.columns
    incoming_cols_by_lower = {c.lower(): c for c in incoming_cols}

    for lc, target_name in target_cols_by_lower.items():
        if lc in incoming_cols_by_lower:
            src_name = incoming_cols_by_lower[lc]
            if src_name != target_name and target_name not in df.columns:
                df = df.withColumnRenamed(src_name, target_name)

    # Refresh after possible renames
    incoming_cols = df.columns
    incoming_set = set(incoming_cols)

    # 2) Cast to target types / add missing cols
    for field in target_schema.fields:
        col_name = field.name
        if col_name in incoming_set:
            df = df.withColumn(col_name, F.col(f"`{col_name}`").cast(field.dataType))
        else:
            df = df.withColumn(col_name, F.lit(None).cast(field.dataType))

    # 3) Exact target order only (drop extras on append)
    df = df.select(*target_cols)
    return df


def append_delta(df: DataFrame, table_name: str):
    """
    Appends to Delta table. If table exists, conform df to target schema first
    to avoid type/casing mismatches (e.g., score int vs bigint).
    """
    if spark.catalog.tableExists(table_name):
        df = _conform_df_to_table_schema(df, table_name)

    (df.write.format("delta")
        .mode("append")
        .saveAsTable(table_name))


def assert_exact_columns(df: DataFrame, expected_cols: List[str], label: str):
    """
    Fail fast if dataframe column order/names do not exactly match the intended schema.
    (Names/order only; types are enforced on append by _conform_df_to_table_schema)
    """
    actual = df.columns
    if actual != expected_cols:
        raise ValueError(
            f"{label} schema mismatch.\nExpected: {expected_cols}\nActual:   {actual}"
        )


def write_current_and_history_exact(
    df_current: DataFrame,
    current_table: str,
    df_history: DataFrame,
    history_table: str
):
    """
    Preferred writer for scorecard tables.

    Assumes:
      - df_current is explicitly shaped for current schema
      - df_history is explicitly shaped for history schema

    Behavior:
      - CURRENT: overwrite (schema can evolve by your block)
      - HISTORY: append if exists (conforms to existing history schema types/casing), else create
    """
    write_delta_overwrite(df_current, current_table)

    if spark.catalog.tableExists(history_table):
        append_delta(df_history, history_table)
    else:
        write_delta_overwrite(df_history, history_table)


# -----------------------------
# Backward-compatible wrapper (optional)
# -----------------------------
def write_current_and_history(
    df: DataFrame,
    current_table: str,
    history_table: str,
    df_history: Optional[DataFrame] = None
):
    """
    Backward-compatible wrapper.

    - Old behavior: write_current_and_history(df, current, history)
      -> uses same df for current and history
    - New behavior: write_current_and_history(df_current, current, history, df_history)
      -> exact current/history shaped dataframes
    """
    if df_history is None:
        write_delta_overwrite(df, current_table)

        if spark.catalog.tableExists(history_table):
            append_delta(df, history_table)
        else:
            write_delta_overwrite(df, history_table)
    else:
        write_current_and_history_exact(df, current_table, df_history, history_table)


# -----------------------------
# Optional debug helper
# -----------------------------
def debug_df_vs_table_types(df: DataFrame, table_name: str):
    """
    Prints case-insensitive type comparison between df and an existing table.
    Helpful when you hit DELTA_FAILED_TO_MERGE_FIELDS.
    """
    print(f"\n=== Debug df vs table: {table_name} ===")
    if not spark.catalog.tableExists(table_name):
        print("Table does not exist.")
        return

    df_types = {f.name.lower(): (f.name, f.dataType.simpleString()) for f in df.schema.fields}
    tb = spark.table(table_name)
    tb_types = {f.name.lower(): (f.name, f.dataType.simpleString()) for f in tb.schema.fields}

    all_keys = sorted(set(df_types.keys()) | set(tb_types.keys()))
    for k in all_keys:
        d = df_types.get(k)
        t = tb_types.get(k)
        if d and t and d[1] != t[1]:
            print(f"TYPE MISMATCH: {d[0]}({d[1]}) vs {t[0]}({t[1]})")
        elif d and not t:
            print(f"ONLY IN DF: {d[0]}({d[1]})")
        elif t and not d:
            print(f"ONLY IN TABLE: {t[0]}({t[1]})")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ### Load full DP list once + derive applicability flags (N/A logic)

# CELL ********************

# --------------------------
# Base DP list (FULL scorecard list)
# --------------------------
dp_gold = spark.table(DP_BASE_TABLE)

dp_base = (
    dp_gold
    .select(
        F.lower(F.trim(F.col("DataProductID"))).alias("DataProductId"),
        F.col("DataProductDisplayName").alias("DataProductDisplayName"),
        F.col("DataProductDescription").alias("DataProductDescription"),
        F.col("ResidencyRegion").alias("ResidencyRegion"),
    )
    .dropDuplicates(["DataProductId"])
)

# --------------------------
# Lightweight categorization from name/description
# --------------------------
txt = F.lower(
    F.concat_ws(
        " ",
        F.coalesce("DataProductDisplayName", F.lit("")),
        F.coalesce("DataProductDescription", F.lit(""))
    )
)

dp_base = (
    dp_base
    .withColumn("IsFabric", txt.contains("fabric"))
    .withColumn("IsS3", txt.contains("amazon s3") | txt.contains(" s3") | txt.contains("s3-") | txt.contains("s3 "))
    .withColumn("IsSqlPaaS", txt.contains("azure sql database") & ~txt.contains("iaas"))
    .withColumn("IsStorage", txt.contains("data lake") | txt.contains("adls") | txt.contains("storage account") | txt.contains("azure files"))
    .withColumn("IsVmLike", txt.contains("iaas") | txt.contains(" vm") | txt.contains("virtual machine") | txt.contains("sap s/4"))
    .withColumn(
        "IsHybridComputeMachine",
        txt.contains("microsoft.hybridcompute/machines")
        | txt.contains("hybridcompute/machines")
        | txt.contains("hybrid compute")
        | txt.contains("azure arc")
        | txt.contains("arc-enabled")
        | txt.contains("arc enabled")
    )
)

# --------------------------
# PII classification (for CC for PII applicability)
# --------------------------
if spark.catalog.tableExists(PII_CLASS_TABLE):
    pii = (spark.table(PII_CLASS_TABLE)
           .select(
               F.lower(F.trim(F.col("DataProductId"))).alias("DataProductId"),
               F.col("HasFullNameClassification").cast("int").alias("HasFullNameClassification"),
               F.col("FullNameColumnCount").cast("int").alias("FullNameColumnCount"),
           )
           .dropDuplicates(["DataProductId"]))
else:
    pii = spark.createDataFrame([], T.StructType([
        T.StructField("DataProductId", T.StringType(), True),
        T.StructField("HasFullNameClassification", T.IntegerType(), True),
        T.StructField("FullNameColumnCount", T.IntegerType(), True),
    ]))

dp_base = (
    dp_base.join(pii, on="DataProductId", how="left")
    .withColumn("HasFullNameClassification", F.coalesce(F.col("HasFullNameClassification"), F.lit(0)))
    .withColumn("FullNameColumnCount", F.coalesce(F.col("FullNameColumnCount"), F.lit(0)))
)

# --------------------------
# Applicability flags (your scoring sheet intent)
# --------------------------
# Tagging: not applicable for S3 (external) -> N/A=100
dp_base = dp_base.withColumn("TagApplicable", ~F.col("IsS3"))

# Residency: "no N/A scenario"
dp_base = dp_base.withColumn("ResidencyApplicable", F.lit(True))

# CC for PII: only meaningful when PII exists; otherwise N/A=100
dp_base = dp_base.withColumn("CCApplicable", F.col("HasFullNameClassification") == 1)

# Defender:
# - applicable for VM / SQL / Storage
# - include Hybrid Compute machines (Azure Arc / Microsoft.HybridCompute/machines)
# - Fabric is N/A
# - S3 external is N/A
dp_base = dp_base.withColumn(
    "DefenderApplicable",
    (~F.col("IsFabric"))
    & (~F.col("IsS3"))
    & (
        F.col("IsVmLike")
        | F.col("IsSqlPaaS")
        | F.col("IsStorage")
        | F.col("IsHybridComputeMachine")
    )
)

dp_ids_all = [r["DataProductId"] for r in dp_base.select("DataProductId").collect()]
print("Total Data Products in scorecard:", len(dp_ids_all))


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ### Tag scorecard (FULL DP list + N/A=100 for S3)

# CELL ********************

# =========================================
# TAG SCORECARD (FULL DP list -> exact current/history schemas)
# =========================================

# Use configured route (must include /api prefix if your ROUTES dict has it)
_tag_route = ROUTES["tag"]

# ---- 1) Call Tag API only for applicable DPs (performance), but output will include ALL DPs ----
tag_eval_ids = [
    r["DataProductId"]
    for r in dp_base.filter(F.col("TagApplicable") == F.lit(True)).select("DataProductId").collect()
]
print("Tag evaluation dp count (applicable only):", len(tag_eval_ids))

tag_rows = []
if len(tag_eval_ids) > 0:
    tag_results = post_batched(_tag_route, tag_eval_ids)

    for item in (tag_results or []):
        dpid = str(item.get("dataProductId") or "").strip().lower()
        if not dpid:
            continue

        res = item.get("resource") or {}
        comp = item.get("compliance") or {}
        breakdown = comp.get("breakdown") or {}
        normalized = comp.get("normalized") or {}
        observed = item.get("observed") or {}

        if not isinstance(res, dict):
            res = {}
        if not isinstance(comp, dict):
            comp = {}
        if not isinstance(breakdown, dict):
            breakdown = {}
        if not isinstance(normalized, dict):
            normalized = {}
        if not isinstance(observed, dict):
            observed = {}

        # Prefer observed from API, fallback to normalized (function returns normalized under compliance.normalized)
        sov_zone_val = observed.get("sovereignty-zone")
        if sov_zone_val is None:
            sov_zone_val = normalized.get("sovereignty-zone")

        res_origin_val = observed.get("resource-origin")
        if res_origin_val is None:
            res_origin_val = normalized.get("resource-origin")

        resource_found = item.get("resourceFound")
        if resource_found is None:
            resource_found = bool(res)

        tag_rows.append({
            "DataProductId": dpid,

            # Resource info
            "ResourceFound": bool(resource_found),
            "ResourceId": res.get("id"),
            "ResourceType": res.get("type"),
            "SubscriptionId": res.get("subscriptionId"),
            "ResourceGroup": res.get("resourceGroup"),
            "Location": (str(res.get("location")).strip().lower() if res.get("location") is not None else None),

            # Observed tag values
            "SovereigntyZone": (str(sov_zone_val).strip().lower() if sov_zone_val is not None and str(sov_zone_val).strip() != "" else None),
            "ResourceOrigin": (str(res_origin_val).strip().lower() if res_origin_val is not None and str(res_origin_val).strip() != "" else None),

            # Breakdown (explicit ints to avoid Delta append type drift)
            "resourceFound20": int(breakdown.get("resourceFound20") or 0),
            "sovereigntyZoneExists20": int(breakdown.get("sovereigntyZoneExists20") or 0),
            "sovereigntyZoneAllowed20": int(breakdown.get("sovereigntyZoneAllowed20") or 0),
            "resourceOriginExists20": int(breakdown.get("resourceOriginExists20") or 0),
            "resourceOriginAllowed20": int(breakdown.get("resourceOriginAllowed20") or 0),

            # Raw score from function
            "ScoreRawApi": int(comp.get("score") or 0),
        })

tag_api_schema = T.StructType([
    T.StructField("DataProductId", T.StringType(), False),

    T.StructField("ResourceFound", T.BooleanType(), True),
    T.StructField("ResourceId", T.StringType(), True),
    T.StructField("ResourceType", T.StringType(), True),
    T.StructField("SubscriptionId", T.StringType(), True),
    T.StructField("ResourceGroup", T.StringType(), True),
    T.StructField("Location", T.StringType(), True),

    T.StructField("SovereigntyZone", T.StringType(), True),
    T.StructField("ResourceOrigin", T.StringType(), True),

    T.StructField("resourceFound20", T.IntegerType(), True),
    T.StructField("sovereigntyZoneExists20", T.IntegerType(), True),
    T.StructField("sovereigntyZoneAllowed20", T.IntegerType(), True),
    T.StructField("resourceOriginExists20", T.IntegerType(), True),
    T.StructField("resourceOriginAllowed20", T.IntegerType(), True),

    T.StructField("ScoreRawApi", T.IntegerType(), True),
])

if tag_rows:
    tag_api = spark.createDataFrame(tag_rows, schema=tag_api_schema).dropDuplicates(["DataProductId"])
else:
    tag_api = spark.createDataFrame([], schema=tag_api_schema)

# ---- 2) Start from FULL DP list and join API results ----
tag_base = (
    dp_base
    .join(tag_api, on="DataProductId", how="left")
    .withColumn("SnapshotTimeUtc", F.current_timestamp())
)

# ---- 3) Scoring / states / reasons (N/A=100 for non-applicable per your approach) ----
tag_out = (
    tag_base
    # Defaults
    .withColumn("ResourceFound", F.coalesce(F.col("ResourceFound"), F.lit(False)).cast("boolean"))
    .withColumn("resourceFound20", F.coalesce(F.col("resourceFound20"), F.lit(0)).cast("int"))
    .withColumn("sovereigntyZoneExists20", F.coalesce(F.col("sovereigntyZoneExists20"), F.lit(0)).cast("int"))
    .withColumn("sovereigntyZoneAllowed20", F.coalesce(F.col("sovereigntyZoneAllowed20"), F.lit(0)).cast("int"))
    .withColumn("resourceOriginExists20", F.coalesce(F.col("resourceOriginExists20"), F.lit(0)).cast("int"))
    .withColumn("resourceOriginAllowed20", F.coalesce(F.col("resourceOriginAllowed20"), F.lit(0)).cast("int"))
    .withColumn("ScoreRawApi", F.coalesce(F.col("ScoreRawApi"), F.lit(0)).cast("int"))

    # Final score (N/A=100 if not applicable)
    .withColumn(
        "ScoreRaw",
        F.when(F.col("TagApplicable") == F.lit(False), F.lit(100))
         .otherwise(F.col("ScoreRawApi"))
         .cast("int")
    )
    .withColumn("TagScorePct", F.col("ScoreRaw").cast("int"))

    # State
    .withColumn(
        "TagState",
        F.when(F.col("TagApplicable") == F.lit(False), F.lit("NotApplicable"))
         .when(F.col("TagScorePct") == 100, F.lit("Compliant"))
         .when(F.col("TagScorePct") >= 60, F.lit("Partial"))
         .otherwise(F.lit("NonCompliant"))
         .cast("string")
    )

    # Reason
    .withColumn(
        "TagReason",
        F.when(
            F.col("TagApplicable") == F.lit(False),
            F.lit("Tag check is not applicable for this data product (external/S3). N/A treated as compliant (100%).")
        )
        .when(
            F.col("ResourceFound") == F.lit(False),
            F.lit("Couldn’t find the Azure resource (dataproductid tag not matched in searched subscriptions).")
        )
        .when(
            F.col("TagScorePct") == 100,
            F.lit("Required tags are present and allowed (sovereignty-zone, resource-origin).")
        )
        .when(
            (F.col("sovereigntyZoneExists20") == 0) & (F.col("resourceOriginExists20") == 0),
            F.lit("Both required tags are missing: sovereignty-zone and resource-origin.")
        )
        .when(
            (F.col("sovereigntyZoneExists20") == 0),
            F.lit("Missing required tag: sovereignty-zone.")
        )
        .when(
            (F.col("resourceOriginExists20") == 0),
            F.lit("Missing required tag: resource-origin.")
        )
        .when(
            (F.col("sovereigntyZoneAllowed20") == 0) & (F.col("resourceOriginAllowed20") == 0),
            F.lit("Both tag values are not allowed: sovereignty-zone and resource-origin.")
        )
        .when(
            (F.col("sovereigntyZoneAllowed20") == 0),
            F.lit("Tag value for sovereignty-zone is not allowed.")
        )
        .when(
            (F.col("resourceOriginAllowed20") == 0),
            F.lit("Tag value for resource-origin is not allowed.")
        )
        .otherwise(F.lit("Tag compliance partially met."))
        .cast("string")
    )
)

# ---------------------------------------
# TAG CHECK - shape EXACT current/history
# ---------------------------------------

# Normalize values used by both outputs
tag_work = (
    tag_out
    .withColumn("ScoreRaw", F.coalesce(F.col("ScoreRaw"), F.lit(0)).cast("int"))
    .withColumn("TagScorePct", F.coalesce(F.col("TagScorePct"), F.lit(0)).cast("int"))
    .withColumn("resourceFound20", F.coalesce(F.col("resourceFound20"), F.lit(0)).cast("int"))
    .withColumn("sovereigntyZoneExists20", F.coalesce(F.col("sovereigntyZoneExists20"), F.lit(0)).cast("int"))
    .withColumn("sovereigntyZoneAllowed20", F.coalesce(F.col("sovereigntyZoneAllowed20"), F.lit(0)).cast("int"))
    .withColumn("resourceOriginExists20", F.coalesce(F.col("resourceOriginExists20"), F.lit(0)).cast("int"))
    .withColumn("resourceOriginAllowed20", F.coalesce(F.col("resourceOriginAllowed20"), F.lit(0)).cast("int"))
    .withColumn("resourceFound", F.coalesce(F.col("ResourceFound"), F.col("resourceFound"), F.lit(False)).cast("boolean"))
    .withColumn("SnapshotTimeUtc", F.current_timestamp())
)

# ---------- CURRENT schema (exact to existing dp_dataproduct_tagcompliance_current)
tag_current_df = tag_work.select(
    F.col("resourceFound20").cast("int").alias("resourceFound20"),
    F.col("sovereigntyZoneExists20").cast("int").alias("sovereigntyZoneExists20"),
    F.col("sovereigntyZoneAllowed20").cast("int").alias("sovereigntyZoneAllowed20"),
    F.col("resourceOriginExists20").cast("int").alias("resourceOriginExists20"),
    F.col("resourceOriginAllowed20").cast("int").alias("resourceOriginAllowed20"),

    F.col("IsFabric").cast("boolean").alias("IsFabric"),
    F.col("IsS3").cast("boolean").alias("IsS3"),
    F.col("IsSqlPaaS").cast("boolean").alias("IsSqlPaaS"),
    F.col("IsStorage").cast("boolean").alias("IsStorage"),
    F.col("IsVmLike").cast("boolean").alias("IsVmLike"),

    F.col("HasFullNameClassification").cast("int").alias("HasFullNameClassification"),
    F.col("FullNameColumnCount").cast("int").alias("FullNameColumnCount"),

    F.col("TagApplicable").cast("boolean").alias("TagApplicable"),
    F.col("ResidencyApplicable").cast("boolean").alias("ResidencyApplicable"),
    F.col("CCApplicable").cast("boolean").alias("CCApplicable"),
    F.col("DefenderApplicable").cast("boolean").alias("DefenderApplicable"),

    F.col("Location").cast("string").alias("Location"),
    F.col("ResourceGroup").cast("string").alias("ResourceGroup"),
    F.col("ResourceOrigin").cast("string").alias("ResourceOrigin"),
    F.col("ResourceType").cast("string").alias("ResourceType"),
    F.col("ScoreRaw").cast("int").alias("ScoreRaw"),
    F.col("SovereigntyZone").cast("string").alias("SovereigntyZone"),
    F.col("SubscriptionId").cast("string").alias("SubscriptionId"),
    F.col("SnapshotTimeUtc").alias("SnapshotTimeUtc"),
    F.col("TagScorePct").cast("int").alias("TagScorePct"),
    F.col("TagState").cast("string").alias("TagState"),
    F.col("TagReason").cast("string").alias("TagReason"),

    F.col("DataProductId").cast("string").alias("dataProductId"),
    F.col("DataProductDisplayName").cast("string").alias("dataProductDisplayName"),
    F.col("DataProductDescription").cast("string").alias("dataProductDescription"),
    F.col("ResidencyRegion").cast("string").alias("residencyRegion"),

    F.col("resourceFound").cast("boolean").alias("resourceFound"),
    F.col("ResourceId").cast("string").alias("resourceId"),
)

tag_current_expected = [
    "resourceFound20","sovereigntyZoneExists20","sovereigntyZoneAllowed20","resourceOriginExists20","resourceOriginAllowed20",
    "IsFabric","IsS3","IsSqlPaaS","IsStorage","IsVmLike","HasFullNameClassification","FullNameColumnCount",
    "TagApplicable","ResidencyApplicable","CCApplicable","DefenderApplicable",
    "Location","ResourceGroup","ResourceOrigin","ResourceType","ScoreRaw","SovereigntyZone","SubscriptionId",
    "SnapshotTimeUtc","TagScorePct","TagState","TagReason",
    "dataProductId","dataProductDisplayName","dataProductDescription","residencyRegion","resourceFound","resourceId"
]
assert_exact_columns(tag_current_df, tag_current_expected, "TAG CURRENT")

# ---------- HISTORY schema (exact to existing dp_dataproduct_tagcompliance_history)
tag_history_df = tag_work.select(
    F.col("DataProductId").cast("string").alias("dataProductId"),
    F.col("DataProductDisplayName").cast("string").alias("dataProductDisplayName"),
    F.col("DataProductDescription").cast("string").alias("dataProductDescription"),
    F.col("ResidencyRegion").cast("string").alias("residencyRegion"),
    F.col("resourceFound").cast("boolean").alias("resourceFound"),
    F.col("ScoreRaw").cast("int").alias("score"),

    F.col("resourceFound20").cast("int").alias("resourceFound20"),
    F.col("sovereigntyZoneExists20").cast("int").alias("sovereigntyZoneExists20"),
    F.col("sovereigntyZoneAllowed20").cast("int").alias("sovereigntyZoneAllowed20"),
    F.col("resourceOriginExists20").cast("int").alias("resourceOriginExists20"),
    F.col("resourceOriginAllowed20").cast("int").alias("resourceOriginAllowed20"),

    F.col("SovereigntyZone").cast("string").alias("sovereignty_zone"),
    F.col("ResourceOrigin").cast("string").alias("resource_origin"),

    F.when(F.col("TagScorePct") == 100, F.lit("compliant"))
     .when(F.col("TagScorePct") >= 60, F.lit("partial"))
     .otherwise(F.lit("noncompliant"))
     .cast("string").alias("complianceStatus"),

    F.col("SnapshotTimeUtc").alias("snapshotTs"),
)

tag_history_expected = [
    "dataProductId","dataProductDisplayName","dataProductDescription","residencyRegion","resourceFound","score",
    "resourceFound20","sovereigntyZoneExists20","sovereigntyZoneAllowed20","resourceOriginExists20","resourceOriginAllowed20",
    "sovereignty_zone","resource_origin","complianceStatus","snapshotTs"
]
assert_exact_columns(tag_history_df, tag_history_expected, "TAG HISTORY")

write_current_and_history_exact(tag_current_df, TAG_CURRENT, tag_history_df, TAG_HISTORY)
print("Wrote TAG current+history")

# Quick validation
print("Base DP count:", dp_base.select("DataProductId").distinct().count())
print("Tag current count:", spark.table(TAG_CURRENT).count())
spark.table(TAG_CURRENT).select(
    "dataProductId", "dataProductDisplayName", "TagApplicable", "resourceFound",
    "ScoreRaw", "TagScorePct", "TagState", "TagReason"
).show(200, truncate=False)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ### Residency scorecard (FULL DP list, no N/A)

# CELL ********************

# =========================================
# RESIDENCY SCORECARD (FULL DP list -> exact current/history schemas)
# =========================================

from pyspark.sql import functions as F
from pyspark.sql import types as T

# ---- Table names / route (expects these constants to already exist, but keeps fallback names) ----
_res_current = globals().get("RES_CURRENT", "dp_dataproduct_residencycompliance_current")
_res_history = globals().get("RES_HISTORY", "dp_dataproduct_residencycompliance_history")
_approved_regions_table = (
    globals().get("APPROVED_REGIONS_TABLE")
    or globals().get("RS_APPROVED_REGIONS_TABLE")
    or "rs_approved_regions"
)
_res_route = ROUTES["residency"]

# ---- Helpers (local to this block) ----
def _pick_first_existing_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _bool_from_approved_expr(col_expr):
    # Handles Yes/No, True/False, 1/0, y/n
    s = F.lower(F.trim(col_expr.cast("string")))
    return (
        F.when(s.isNull(), F.lit(None).cast("boolean"))
         .when(s.isin("yes", "y", "true", "1"), F.lit(True))
         .when(s.isin("no", "n", "false", "0"), F.lit(False))
         .otherwise(F.lit(None).cast("boolean"))
    )

# ---- 1) Read approved regions ruleset (region name/code + approved flag) ----
if not spark.catalog.tableExists(_approved_regions_table):
    raise ValueError(f"Approved regions table not found: {_approved_regions_table}")

ar_raw = spark.table(_approved_regions_table)

# Support multiple possible column namings from your temporary ruleset tables
ar_name_col = _pick_first_existing_col(ar_raw, ["Region Name", "RegionName", "region_name", "regionName"])
ar_code_col = _pick_first_existing_col(ar_raw, ["Region Code", "RegionCode", "region_code", "regionCode"])
ar_appr_col = _pick_first_existing_col(ar_raw, ["Approved", "approved", "IsApproved", "isApproved"])

if not ar_name_col or not ar_code_col or not ar_appr_col:
    raise ValueError(
        f"Could not resolve approved region columns in {_approved_regions_table}. "
        f"Found columns: {ar_raw.columns}"
    )

approved_regions = (
    ar_raw
    .select(
        F.trim(F.col(f"`{ar_name_col}`")).alias("ApprovedRegionName"),
        F.lower(F.trim(F.col(f"`{ar_code_col}`"))).alias("ApprovedRegionCode"),
        _bool_from_approved_expr(F.col(f"`{ar_appr_col}`")).alias("ApprovedFlag")
    )
    .filter(F.col("ApprovedRegionCode").isNotNull() & (F.col("ApprovedRegionCode") != ""))
    .dropDuplicates(["ApprovedRegionCode"])
)

# Keep only approved rows for mapping/scoring
approved_yes = approved_regions.filter(F.coalesce(F.col("ApprovedFlag"), F.lit(False)) == F.lit(True))

# Two lookups: by code and by name (to support either glossary style)
approved_by_code = (
    approved_yes
    .select(
        F.col("ApprovedRegionCode").alias("lk_code"),
        F.col("ApprovedRegionName").alias("lk_name_from_code"),
        F.col("ApprovedRegionCode").alias("lk_code_from_code"),
        F.lit(True).alias("lk_approved_from_code")
    )
)

approved_by_name = (
    approved_yes
    .select(
        F.lower(F.trim(F.col("ApprovedRegionName"))).alias("lk_name"),
        F.col("ApprovedRegionName").alias("lk_name_from_name"),
        F.col("ApprovedRegionCode").alias("lk_code_from_name"),
        F.lit(True).alias("lk_approved_from_name")
    )
    .dropDuplicates(["lk_name"])
)

# ---- 2) Call residency compliance function for ALL DPs (full scorecard list) ----
# dp_ids_all must already be built from your dp_base block
api_results = post_batched(_res_route, dp_ids_all)

# ---- 3) Normalize API results into a compact dataframe (one row per DP) ----
rows = []
for r in (api_results or []):
    dpid = str(r.get("dataProductId") or "").strip().lower()
    if not dpid:
        continue

    resources = r.get("resources") or []
    locations = r.get("locations") or []

    # Normalize distinct lowercase locations
    norm_locations = sorted(list({
        str(x).strip().lower()
        for x in locations
        if str(x or "").strip()
    }))

    # Resource IDs as sorted distinct strings
    resource_ids = sorted(list({
        str(x.get("id")).strip()
        for x in resources
        if isinstance(x, dict) and str(x.get("id") or "").strip()
    }))

    # Fallback count if resourceCount missing
    resource_count = r.get("resourceCount")
    if resource_count is None:
        resource_count = len(resources)

    resource_found = r.get("resourceFound")
    if resource_found is None:
        resource_found = bool(resource_count and int(resource_count) > 0)

    rows.append({
        "DataProductId": dpid,
        "AzureResourceFound": bool(resource_found),
        "AzureResourceCount": int(resource_count or 0),
        "AzureLocations": ",".join(norm_locations),     # exact table wants string
        "AzureResourceIds": ",".join(resource_ids),     # exact table wants string
    })

api_schema = T.StructType([
    T.StructField("DataProductId", T.StringType(), True),
    T.StructField("AzureResourceFound", T.BooleanType(), True),
    T.StructField("AzureResourceCount", T.IntegerType(), True),
    T.StructField("AzureLocations", T.StringType(), True),
    T.StructField("AzureResourceIds", T.StringType(), True),
])

if rows:
    res_api = spark.createDataFrame(rows, schema=api_schema).dropDuplicates(["DataProductId"])
else:
    res_api = spark.createDataFrame([], schema=api_schema)

# ---- 3b) S3 fallback (Phase 2): if no Azure resource found for an S3 DP, look up AWS bucket location ----
# Assumption for Phase 2: S3 bucket name == DataProductDisplayName in dp_dataproductresidency_gold (dp_base)
_s3_route = "/api/azure/residencyComplianceAws"
_s3_url = FUNCTION_BASE_URL.rstrip("/") + _s3_route

def _get_s3_bucket_location(bucket_name: str, aws_region: str = "us-east-1") -> Optional[Dict[str, Any]]:
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    params = {"bucketName": bucket_name, "region": aws_region}
    r = requests.get(_s3_url, headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"S3 lookup failed for bucket={bucket_name}: {r.status_code} {r.text[:500]}")
    return r.json()

# Identify S3 DPs where the Azure resource lookup returned nothing
s3_missing = (
    dp_base.alias("b")
    .join(res_api.alias("a"), on="DataProductId", how="left")
    .filter((F.col("b.IsS3") == F.lit(True)) & (F.coalesce(F.col("a.AzureResourceFound"), F.lit(False)) == F.lit(False)))
    .select("b.DataProductId", "b.DataProductDisplayName")
    .collect()
)

s3_rows = []
for r in s3_missing:
    dpid = r["DataProductId"]
    bucket_name = r["DataProductDisplayName"]
    if not bucket_name:
        continue
    out = _get_s3_bucket_location(str(bucket_name), "us-east-1")  # Phase 2: fixed region input
    bucket_loc = str(out.get("bucketLocation") or "").strip().lower()
    bucket_arn = str(out.get("bucketArn") or "").strip()
    if not bucket_loc:
        continue
    s3_rows.append({
        "DataProductId": str(dpid).strip().lower(),
        "AzureResourceFound": True,                 # reuse existing scoring logic (generic "resource found")
        "AzureResourceCount": 1,
        "AzureLocations": bucket_loc,
        "AzureResourceIds": bucket_arn,
    })

if s3_rows:
    s3_schema = T.StructType([
        T.StructField("DataProductId", T.StringType(), True),
        T.StructField("AzureResourceFound", T.BooleanType(), True),
        T.StructField("AzureResourceCount", T.IntegerType(), True),
        T.StructField("AzureLocations", T.StringType(), True),
        T.StructField("AzureResourceIds", T.StringType(), True),
    ])
    s3_df = spark.createDataFrame(s3_rows, schema=s3_schema).dropDuplicates(["DataProductId"])

    # Override empty Azure results with S3-derived location for these DPs
    res_api = (
        res_api.alias("a")
        .join(s3_df.alias("s"), on="DataProductId", how="left")
        .select(
            F.col("DataProductId"),
            F.coalesce(F.col("s.AzureResourceFound"), F.col("a.AzureResourceFound")).alias("AzureResourceFound"),
            F.coalesce(F.col("s.AzureResourceCount"), F.col("a.AzureResourceCount")).alias("AzureResourceCount"),
            F.coalesce(F.col("s.AzureLocations"), F.col("a.AzureLocations")).alias("AzureLocations"),
            F.coalesce(F.col("s.AzureResourceIds"), F.col("a.AzureResourceIds")).alias("AzureResourceIds"),
        )
    )

# ---- 4) Start from FULL dp_base and join API + approved region lookups ----
res_base = (
    dp_base
    .select(
        "DataProductId",
        "DataProductDisplayName",
        "DataProductDescription",
        "ResidencyRegion"
    )
    .withColumn("GlossaryResidencyInput", F.trim(F.col("ResidencyRegion")))
    .withColumn("GlossaryResidencyInputNorm", F.lower(F.trim(F.coalesce(F.col("ResidencyRegion"), F.lit("")))))
    .join(res_api, on="DataProductId", how="left")
    .join(approved_by_code, F.col("GlossaryResidencyInputNorm") == F.col("lk_code"), "left")
    .join(approved_by_name, F.col("GlossaryResidencyInputNorm") == F.col("lk_name"), "left")
)

# ---- 5) Derive canonical glossary residency + scoring fields ----
# Missing glossary residency definition (handles null/blank/"unknown (not assigned)")
is_glossary_missing = (
    F.col("GlossaryResidencyInput").isNull()
    | (F.trim(F.col("GlossaryResidencyInput")) == "")
    | (F.lower(F.trim(F.col("GlossaryResidencyInput"))).isin("unknown", "unknown (not assigned)", "undefined"))
)

res_scored = (
    res_base
    .withColumn("SnapshotTimeUtc", F.current_timestamp())

    # Canonical glossary residency region name/code
    .withColumn(
        "GlossaryResidencyRegionCode",
        F.coalesce(
            F.col("lk_code_from_code"),
            F.col("lk_code_from_name"),
            # fallback: if glossary already looks like code, keep lowercase text
            F.when(~is_glossary_missing, F.lower(F.trim(F.col("GlossaryResidencyInput"))))
             .otherwise(F.lit(None).cast("string"))
        )
    )
    .withColumn(
        "GlossaryResidencyRegionName",
        F.coalesce(
            F.col("lk_name_from_code"),
            F.col("lk_name_from_name"),
            F.when(~is_glossary_missing, F.col("GlossaryResidencyInput"))
             .otherwise(F.lit(None).cast("string"))
        )
    )
    .withColumn("GlossaryResidencyMissing", is_glossary_missing.cast("boolean"))
    .withColumn(
        "IsApprovedResidency",
        F.when(F.col("GlossaryResidencyMissing"), F.lit(False))
         .otherwise(F.coalesce(F.col("lk_approved_from_code"), F.col("lk_approved_from_name"), F.lit(False)))
         .cast("boolean")
    )

    # API defaults (full scorecard rows even if API returns no match)
    .withColumn("AzureResourceFound", F.coalesce(F.col("AzureResourceFound"), F.lit(False)).cast("boolean"))
    .withColumn("AzureResourceCount", F.coalesce(F.col("AzureResourceCount"), F.lit(0)).cast("int"))
    .withColumn("AzureLocations", F.coalesce(F.col("AzureLocations"), F.lit("")).cast("string"))
    .withColumn("AzureResourceIds", F.coalesce(F.col("AzureResourceIds"), F.lit("")).cast("string"))
)

# Strict match rule (case-insensitive, strict string equality)
res_scored = res_scored.withColumn(
    "AzureLocationMatch",
    (
        (F.col("AzureResourceFound") == F.lit(True)) &
        (~F.col("GlossaryResidencyMissing")) &
        (F.col("IsApprovedResidency") == F.lit(True)) &
        (
            F.lower(F.trim(F.col("AzureLocations"))) ==
            F.lower(F.trim(F.coalesce(F.col("GlossaryResidencyRegionCode"), F.lit(""))))
        )
    ).cast("boolean")
)

# ---- Residency scoring using the rubric (0/25/50/75/100) ----
res_scored = (
    res_scored
    .withColumn(
        "ResidencyScorePct",
        F.when(~F.col("AzureResourceFound"), F.lit(0))                       # 0%: no Azure/S3 resource
         .when(F.col("GlossaryResidencyMissing"), F.lit(25))                 # 25%: resource found, glossary missing
         .when(~F.col("IsApprovedResidency"), F.lit(50))                     # 50%: glossary present, not approved
         .when(~F.col("AzureLocationMatch"), F.lit(75))                      # 75%: approved, but mismatch to resource region
         .otherwise(F.lit(100))                                              # 100%: approved and matches resource region
         .cast("int")
    )
    .withColumn(
        "ResidencyScoreReason",
        F.when(~F.col("AzureResourceFound"),
               F.lit("Could not find Data Product's associated Azure or AWS S3 resource using the dataproductid tag"))
         .when(F.col("GlossaryResidencyMissing"),
               F.lit("Found associated Azure/S3 resource but Purview is missing residency (glossary) as per dp_dataproductresidency_gold"))
         .when(~F.col("IsApprovedResidency"),
               F.lit("Found associated Azure/S3 resource + Purview residency (glossary) present, but does not match approved region list (rs_approved_regions)"))
         .when(~F.col("AzureLocationMatch"),
               F.lit("Found associated Azure/S3 resource + Purview residency present and approved, but does not match the associated resource's region"))
         .otherwise(
               F.lit("Found associated Azure/S3 resource + Purview residency present and approved + matches the associated resource's region"))
         .cast("string")
    )
)

# ---- 6) Shape EXACT current/history schemas (same schema for both residency tables) ----
res_current_df = res_scored.select(
    F.col("SnapshotTimeUtc").alias("SnapshotTimeUtc"),
    F.col("DataProductId").cast("string").alias("DataProductID"),
    F.col("DataProductDisplayName").cast("string").alias("DataProductDisplayName"),
    F.col("DataProductDescription").cast("string").alias("DataProductDescription"),
    F.col("GlossaryResidencyRegionName").cast("string").alias("GlossaryResidencyRegionName"),
    F.col("GlossaryResidencyRegionCode").cast("string").alias("GlossaryResidencyRegionCode"),
    F.col("GlossaryResidencyMissing").cast("boolean").alias("GlossaryResidencyMissing"),
    F.col("IsApprovedResidency").cast("boolean").alias("IsApprovedResidency"),
    F.col("AzureResourceFound").cast("boolean").alias("AzureResourceFound"),
    F.col("AzureResourceCount").cast("int").alias("AzureResourceCount"),
    F.col("AzureLocations").cast("string").alias("AzureLocations"),
    F.col("AzureResourceIds").cast("string").alias("AzureResourceIds"),
    F.col("AzureLocationMatch").cast("boolean").alias("AzureLocationMatch"),
    F.col("ResidencyScorePct").cast("int").alias("ResidencyScorePct"),
    F.col("ResidencyScoreReason").cast("string").alias("ResidencyScoreReason"),
)

res_expected = [
    "SnapshotTimeUtc",
    "DataProductID",
    "DataProductDisplayName",
    "DataProductDescription",
    "GlossaryResidencyRegionName",
    "GlossaryResidencyRegionCode",
    "GlossaryResidencyMissing",
    "IsApprovedResidency",
    "AzureResourceFound",
    "AzureResourceCount",
    "AzureLocations",
    "AzureResourceIds",
    "AzureLocationMatch",
    "ResidencyScorePct",
    "ResidencyScoreReason",
]

assert_exact_columns(res_current_df, res_expected, "RESIDENCY CURRENT")

# history table has same schema in your environment
res_history_df = res_current_df.select(*res_expected)
assert_exact_columns(res_history_df, res_expected, "RESIDENCY HISTORY")

# ---- 7) Write current + history ----
# CURRENT: overwrite (allows schema evolution)
write_delta_overwrite(res_current_df, _res_current)

# HISTORY: if schema changed (AzureLocations -> AzureLocations), overwrite once; otherwise append
if spark.catalog.tableExists(_res_history):
    hist_cols = spark.table(_res_history).columns
    if "AzureLocations" not in hist_cols:
        print(f"History schema migration detected for {_res_history} (writing overwrite).")
        write_delta_overwrite(res_history_df, _res_history)
    else:
        append_delta(res_history_df, _res_history)
else:
    write_delta_overwrite(res_history_df, _res_history)

print(f"Wrote RESIDENCY current+history -> {_res_current}, {_res_history}")

# ---- 8) Quick validation ----
print("Base DP count:", dp_base.select('DataProductId').distinct().count())
print("Residency current count:", spark.table(_res_current).count())
spark.table(_res_current).select(
    "DataProductID", "DataProductDisplayName",
    "GlossaryResidencyRegionCode", "AzureLocations",
    "AzureLocationMatch", "ResidencyScorePct", "ResidencyScoreReason"
).show(200, truncate=False)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ### CC for PII scorecard (FULL DP list; non-PII → N/A=100)

# CELL ********************

# =========================================
# CC CHECK SCORECARD (FULL DP list -> exact current/history schemas)
# =========================================

from pyspark.sql import functions as F
from pyspark.sql import types as T

# ---- 0) Ruleset: approved CC SKUs ----
# Assumes CC_SKUS_TABLE has columns: sku, is_approved
# Normalize SKU text and collapse duplicates deterministically:
# if the same sku appears multiple times, treat it as approved if ANY row is approved.
cc_skus = (
    spark.table(CC_SKUS_TABLE)
    .select(
        F.lower(F.trim(F.col("sku"))).alias("sku_lc"),
        F.coalesce(F.col("is_approved").cast("boolean"), F.lit(False)).alias("sku_is_approved")
    )
    .filter(F.col("sku_lc").isNotNull() & (F.col("sku_lc") != ""))
    .groupBy("sku_lc")
    .agg(
        F.max(F.col("sku_is_approved").cast("int")).alias("sku_is_approved_int")
    )
    .withColumn("sku_is_approved", (F.col("sku_is_approved_int") == F.lit(1)).cast("boolean"))
    .drop("sku_is_approved_int")
)

# ---- 1) Evaluate CC API only for PII-applicable DPs (performance), but output must include ALL DPs ----
cc_eval_ids = [
    r["DataProductId"]
    for r in dp_base.filter(F.col("CCApplicable") == F.lit(True))
                    .select("DataProductId")
                    .distinct()
                    .collect()
]
print("CC evaluation dp count (PII-only):", len(cc_eval_ids))

cc_rows = []
if len(cc_eval_ids) > 0:
    cc_results = post_batched(ROUTES["cc"], cc_eval_ids)

    for item in (cc_results or []):
        dp = str(item.get("dataProductId") or "").strip().lower()
        if not dp:
            continue

        res = item.get("resource") or {}
        vm = item.get("vm") or {}
        arc = item.get("arc") or {}
        det = item.get("details") or {}

        if not isinstance(res, dict): res = {}
        if not isinstance(vm, dict): vm = {}
        if not isinstance(arc, dict): arc = {}
        if not isinstance(det, dict): det = {}

        # New function payload fields (Arc + unified lookup). Fall back to legacy VM-only shape if absent.
        cc_resource_kind = item.get("ccResourceKind")
        cc_lookup_sku = item.get("ccLookupSku")
        cc_lookup_sku_source = item.get("ccLookupSkuSource")

        vm_size = vm.get("vmSize")

        # Backward-compatible generic lookup:
        # - Prefer new unified ccLookupSku (Azure VM size OR Arc model)
        # - Else fall back to legacy vm.vmSize
        lookup_sku_raw = cc_lookup_sku if cc_lookup_sku is not None else vm_size

        # For schema compatibility, continue populating VmSize column, but now store the generic lookup
        # value (Azure VM size OR Arc model) so reporting remains useful without schema changes.
        vm_size_compat = lookup_sku_raw

        cc_rows.append({
            "DataProductId": dp,
            "resourceFound": bool(item.get("resourceFound", False)),
            "vmApplicable": item.get("vmApplicable"),  # True/False/None (compatibility field)

            "ResourceId": res.get("id"),
            "ResourceType": res.get("type"),
            "SubscriptionId": res.get("subscriptionId"),
            "ResourceGroup": res.get("resourceGroup"),
            "Location": (str(res.get("location")).strip().lower() if res.get("location") is not None else None),

            # Legacy/compat columns
            "VmSize": vm_size_compat,        # Azure VM size OR Arc model
            "SecurityType": vm.get("securityType"),

            # New parsed fields from updated function app response
            "CCResourceKind": cc_resource_kind,
            "CCLookupSku": cc_lookup_sku,
            "CCLookupSkuSource": cc_lookup_sku_source,

            "ArcModel": arc.get("model"),
            "ArcCloudProvider": arc.get("cloudProvider"),
            "ArcManufacturer": arc.get("manufacturer"),
            "ArcStatus": arc.get("status"),
            "ArcOsType": arc.get("osType"),
            "ArcOsSku": arc.get("osSku"),

            "DetailsNote": det.get("note"),
            "ArmError": det.get("armError"),
            "LastUpdateScanUtc": item.get("LastUpdateScanUtc"),
            "PendingUpdatesTotal": item.get("PendingUpdatesTotal"),
            "PatchAssessmentStatus": item.get("PatchAssessmentStatus"),
        })

cc_api_schema = T.StructType([
    T.StructField("DataProductId", T.StringType(), False),
    T.StructField("resourceFound", T.BooleanType(), True),
    T.StructField("vmApplicable", T.BooleanType(), True),
    T.StructField("ResourceId", T.StringType(), True),
    T.StructField("ResourceType", T.StringType(), True),
    T.StructField("SubscriptionId", T.StringType(), True),
    T.StructField("ResourceGroup", T.StringType(), True),
    T.StructField("Location", T.StringType(), True),
    T.StructField("VmSize", T.StringType(), True),  # compatibility: now Azure VM size OR Arc model
    T.StructField("SecurityType", T.StringType(), True),

    # New parsed fields (internal scoring/debug)
    T.StructField("CCResourceKind", T.StringType(), True),
    T.StructField("CCLookupSku", T.StringType(), True),
    T.StructField("CCLookupSkuSource", T.StringType(), True),
    T.StructField("ArcModel", T.StringType(), True),
    T.StructField("ArcCloudProvider", T.StringType(), True),
    T.StructField("ArcManufacturer", T.StringType(), True),
    T.StructField("ArcStatus", T.StringType(), True),
    T.StructField("ArcOsType", T.StringType(), True),
    T.StructField("ArcOsSku", T.StringType(), True),

    T.StructField("DetailsNote", T.StringType(), True),
    T.StructField("ArmError", T.StringType(), True),
    T.StructField("LastUpdateScanUtc", T.StringType(), True),
    T.StructField("PendingUpdatesTotal", T.IntegerType(), True),
    T.StructField("PatchAssessmentStatus", T.StringType(), True),
])

if cc_rows:
    cc_api = spark.createDataFrame(cc_rows, schema=cc_api_schema).dropDuplicates(["DataProductId"])
else:
    cc_api = spark.createDataFrame([], cc_api_schema)

# ---- 2) Join to FULL DP list (scorecard must include all DPs) ----
cc_base = (
    dp_base
    .select(
        "DataProductId",
        "DataProductDisplayName",
        "HasFullNameClassification",
        "FullNameColumnCount",
        "CCApplicable"
    )
    .join(cc_api, on="DataProductId", how="left")
    .withColumn("SnapshotUtc", F.current_timestamp())
    .withColumn("resourceFound", F.coalesce(F.col("resourceFound"), F.lit(False)).cast("boolean"))
    .withColumn("vmApplicable", F.col("vmApplicable").cast("boolean"))
    .withColumn("Location", F.when(F.col("Location").isNotNull(), F.lower(F.trim(F.col("Location")))).otherwise(F.lit(None).cast("string")))
    # Normalize resource kind/type flags (function app already sets vmApplicable=True for Azure VM or Arc machine)
    .withColumn("ResourceType_lc", F.lower(F.trim(F.col("ResourceType"))))
    .withColumn("CCResourceKind_lc", F.lower(F.trim(F.col("CCResourceKind"))))
    .withColumn(
        "IsArcMachine",
        (
            (F.col("ResourceType_lc") == F.lit("microsoft.hybridcompute/machines")) |
            (F.col("CCResourceKind_lc") == F.lit("arcmachine"))
        ).cast("boolean")
    )
    .withColumn(
        "IsAzureVmResource",
        (
            (F.col("ResourceType_lc") == F.lit("microsoft.compute/virtualmachines")) |
            (F.col("CCResourceKind_lc") == F.lit("azurevm"))
        ).cast("boolean")
    )
    # Unified lookup value for CC scoring: Azure VM size OR Arc model
    .withColumn("LookupSkuRaw", F.coalesce(F.col("CCLookupSku"), F.col("VmSize")))
    .withColumn(
        "LookupSkuRaw",
        F.when(F.col("LookupSkuRaw").isNotNull(), F.trim(F.col("LookupSkuRaw"))).otherwise(F.lit(None).cast("string"))
    )
)

# ---- 3) Join CC SKU ruleset (normalized case/trim + require is_approved later in scoring) ----
cc_base = (
    cc_base
    .withColumn("LookupSku_lc", F.lower(F.trim(F.col("LookupSkuRaw"))))
    .join(cc_skus, F.col("LookupSku_lc") == cc_skus.sku_lc, "left")
    .withColumn("IsConfidentialSku", F.col("sku_lc").isNotNull())
    .withColumn(
        "IsApprovedSkuCalc",
        F.when(F.col("sku_lc").isNotNull(), F.coalesce(F.col("sku_is_approved"), F.lit(False)))
         .otherwise(F.lit(False))
         .cast("boolean")
    )
)

# ---- 4) Score using your CC rubric (Azure VM + Arc machine; region intentionally ignored) ----
# Scoring rubric:
# 0   = resource not found
# 25  = found CC-applicable resource (Azure VM/Arc), but Azure VM size unavailable (legacy/ARM issue state)
# 50  = not confidential compute, OR Arc model property null/empty
# 75  = confidential compute SKU/model found, but not approved (is_approved = false)
# 100 = approved confidential compute SKU/model
# N/A = 100 for non-PII or non-applicable resource type
cc_scored = (
    cc_base
    .withColumn(
        "LookupSkuMissing",
        (F.col("LookupSkuRaw").isNull() | (F.trim(F.col("LookupSkuRaw")) == F.lit(""))).cast("boolean")
    )
    .withColumn(
        "CCForPIIStatus",
        F.when(F.col("CCApplicable") == F.lit(False), F.lit("NA_NotPII"))                    # N/A=100
         .when(F.col("resourceFound") == F.lit(False), F.lit("NotFound"))                    # 0%
         .when((F.col("resourceFound") == F.lit(True)) & (F.col("vmApplicable") == F.lit(False)),
               F.lit("NA_NotApplicable"))                                                     # N/A=100
         .when((F.col("resourceFound") == F.lit(True)) & (F.col("vmApplicable") == F.lit(True)),
               F.lit("Applicable"))
         .otherwise(F.lit("Unknown"))
    )
    .withColumn(
        "CCForPIIScore",
        F.when(F.col("CCApplicable") == F.lit(False), F.lit(100))                            # N/A=100
         .when(F.col("resourceFound") == F.lit(False), F.lit(0))                             # Couldn't find resource
         .when((F.col("resourceFound") == F.lit(True)) & (F.col("vmApplicable") == F.lit(False)),
               F.lit(100))                                                                    # N/A=100
         .when((F.col("resourceFound") == F.lit(True)) & (F.col("vmApplicable") == F.lit(True)),
               F.when((F.col("IsArcMachine") == F.lit(True)) & (F.col("LookupSkuMissing") == F.lit(True)), F.lit(50))
                .when((F.col("IsAzureVmResource") == F.lit(True)) & (F.col("LookupSkuMissing") == F.lit(True)), F.lit(25))
                .when(F.col("IsConfidentialSku") == F.lit(False), F.lit(50))
                .when((F.col("IsConfidentialSku") == F.lit(True)) & (F.col("IsApprovedSkuCalc") == F.lit(False)), F.lit(75))
                .when((F.col("IsConfidentialSku") == F.lit(True)) & (F.col("IsApprovedSkuCalc") == F.lit(True)), F.lit(100))
                .otherwise(F.lit(25))
         )
         .otherwise(F.lit(100))
         .cast("int")
    )
    .withColumn(
        "Reason",
        F.when(F.col("CCApplicable") == F.lit(False),
               F.lit("The azure resource is not applicable for confidential compute. N/A is a 100% score"))
         .when(F.col("resourceFound") == F.lit(False),
               F.lit("Couldn’t find the respective azure resource for the data product"))
         .when((F.col("resourceFound") == F.lit(True)) & (F.col("vmApplicable") == F.lit(False)),
               F.lit("The azure resource is not applicable for confidential compute. N/A is a 100% score"))
         .when((F.col("resourceFound") == F.lit(True)) & (F.col("vmApplicable") == F.lit(True)) &
               (F.col("IsArcMachine") == F.lit(True)) & (F.col("LookupSkuMissing") == F.lit(True)),
               F.lit("Found the resource but not running confidential compute or arc model property is null/empty"))
         .when((F.col("resourceFound") == F.lit(True)) & (F.col("vmApplicable") == F.lit(True)) &
               (F.col("IsAzureVmResource") == F.lit(True)) & (F.col("LookupSkuMissing") == F.lit(True)),
               F.lit("Found the azure/arc/sql vm resource and it is a confidential compute applicable resource (azure vm or arc machine)"))
         .when((F.col("resourceFound") == F.lit(True)) & (F.col("vmApplicable") == F.lit(True)) & (F.col("IsConfidentialSku") == F.lit(False)),
               F.lit("Found the resource but not running confidential compute"))
         .when((F.col("resourceFound") == F.lit(True)) & (F.col("vmApplicable") == F.lit(True)) &
               (F.col("IsConfidentialSku") == F.lit(True)) & (F.col("IsApprovedSkuCalc") == F.lit(False)),
               F.lit("Found the resource but not running the approved confidential compute sku"))
         .otherwise(F.lit("Found the resource running the approved confidential compute sku"))
         .cast("string")
    )
)

# ---- 5) Shape EXACT current/history schema (same schema for both CC tables) ----
cc_current_df = cc_scored.select(
    F.col("SnapshotUtc").alias("SnapshotUtc"),
    F.col("DataProductId").cast("string").alias("DataProductId"),
    F.col("DataProductDisplayName").cast("string").alias("DataProductDisplayName"),
    F.coalesce(F.col("HasFullNameClassification").cast("int"), F.lit(0)).alias("HasFullNameClassification"),
    F.coalesce(F.col("FullNameColumnCount").cast("int"), F.lit(0)).alias("FullNameColumnCount"),
    F.col("CCForPIIScore").cast("int").alias("CCForPIIScore"),
    F.col("CCForPIIStatus").cast("string").alias("CCForPIIStatus"),
    F.col("Reason").cast("string").alias("Reason"),
    F.col("ResourceId").cast("string").alias("ResourceId"),
    F.col("ResourceType").cast("string").alias("ResourceType"),
    F.col("SubscriptionId").cast("string").alias("SubscriptionId"),
    F.col("ResourceGroup").cast("string").alias("ResourceGroup"),
    F.col("Location").cast("string").alias("Location"),
    F.col("VmSize").cast("string").alias("VmSize"),  # now may contain Arc model for compatibility
    F.col("SecurityType").cast("string").alias("SecurityType"),
    F.when(F.col("CCApplicable") == F.lit(False), F.lit(False))
     .otherwise(F.coalesce(F.col("IsApprovedSkuCalc"), F.lit(False)))
     .cast("boolean")
     .alias("IsApprovedSku"),
    F.lit(None).cast("boolean").alias("IsApprovedRegion"),   # retained for schema compatibility; region not used in current CC scoring
    F.col("DetailsNote").cast("string").alias("DetailsNote"),
    F.col("ArmError").cast("string").alias("ArmError"),
    F.to_timestamp(F.col("LastUpdateScanUtc")).alias("LastUpdateScanUtc"),
    F.col("PendingUpdatesTotal").cast("int").alias("PendingUpdatesTotal"),
    F.col("PatchAssessmentStatus").cast("string").alias("PatchAssessmentStatus"),
)

cc_expected = [
    "SnapshotUtc",
    "DataProductId",
    "DataProductDisplayName",
    "HasFullNameClassification",
    "FullNameColumnCount",
    "CCForPIIScore",
    "CCForPIIStatus",
    "Reason",
    "ResourceId",
    "ResourceType",
    "SubscriptionId",
    "ResourceGroup",
    "Location",
    "VmSize",
    "SecurityType",
    "IsApprovedSku",
    "IsApprovedRegion",
    "DetailsNote",
    "ArmError",
    "LastUpdateScanUtc",
    "PendingUpdatesTotal",
    "PatchAssessmentStatus",
]

assert_exact_columns(cc_current_df, cc_expected, "CC CURRENT")

# history table has same schema in your environment
cc_history_df = cc_current_df.select(*cc_expected)
assert_exact_columns(cc_history_df, cc_expected, "CC HISTORY")

# ---- 6) Write current + history using exact-schema helper ----
write_current_and_history_exact(cc_current_df, CC_CURRENT, cc_history_df, CC_HISTORY)
print(f"Wrote CC current+history -> {CC_CURRENT}, {CC_HISTORY}")

# ---- 7) Quick validation ----
print("Base DP count:", dp_base.select("DataProductId").distinct().count())
print("CC current count:", spark.table(CC_CURRENT).count())
spark.table(CC_CURRENT).select(
    "DataProductId", "DataProductDisplayName", "HasFullNameClassification",
    "CCForPIIStatus", "CCForPIIScore", "Reason", "ResourceType", "VmSize", "IsApprovedSku",
    "LastUpdateScanUtc", "PendingUpdatesTotal", "PatchAssessmentStatus"
).show(200, truncate=False)



# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

#  Build the owner link dataframe from SSA DataProductOwner

# CELL ********************

from pyspark.sql import functions as F, types as T
from datetime import datetime, timezone

# --- CONFIG ---
DATA_PRODUCT_OWNER_PATH = "Files/purview_meta_data/DomainModel/DataProductOwner"

# Optional demo fallback (use your email if Graph resolution is not available yet)
OWNER_EMAIL_DEMO_FALLBACK = "your_email@yourdomain.com"   # <-- change if needed
OWNER_NAME_DEMO_FALLBACK  = "Demo Owner"

# --- LOAD SSA owner mapping (1:1 assumed) ---
dpo_raw = spark.read.format("delta").load(DATA_PRODUCT_OWNER_PATH)

dpo = (
    dpo_raw
    .select(
        F.lower(F.trim(F.col("DataProductId"))).alias("DataProductId"),
        F.trim(F.col("DataProductOwnerId")).alias("OwnerObjectId")
    )
    .filter(F.col("DataProductId").isNotNull() & (F.col("DataProductId") != ""))
    .filter(F.col("OwnerObjectId").isNotNull() & (F.col("OwnerObjectId") != ""))
    .dropDuplicates(["DataProductId"])   # 1:1 assumption
)

print("SSA DataProductOwner rows:", dpo.count())
display(dpo.limit(20))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Graph test with a graceful “skip Graph” cell. For demo, we will fall back to demo owner (Moaz's)} email for any entra user assigned as the data product owner.

# CELL ********************

from pyspark.sql import functions as F, types as T
from datetime import datetime, timezone

# ---- DEMO FALLBACK CONFIG (update these) ----
OWNER_EMAIL_DEMO_FALLBACK = "<owner_email>"   # <-- change this
OWNER_NAME_DEMO_FALLBACK  = "Demo Owner"

# We are intentionally skipping Graph resolution for now in Fabric notebook
GRAPH_RESOLUTION_ENABLED = False

print("Graph resolution enabled?", GRAPH_RESOLUTION_ENABLED)
print("Proceeding with demo fallback owner email/name while preserving OwnerObjectId from SSA.")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Build owner contact rows from fallback only

# CELL ********************

# Distinct owner IDs from SSA mapping
owner_ids = [r["OwnerObjectId"] for r in dpo.select("OwnerObjectId").dropDuplicates().collect()]
print("Distinct owner object IDs:", len(owner_ids))

resolved_rows = []
for oid in owner_ids:
    resolved_rows.append({
        "OwnerObjectId": oid,
        "OwnerName": OWNER_NAME_DEMO_FALLBACK,
        "OwnerEmail": OWNER_EMAIL_DEMO_FALLBACK,
        "OwnerUpn": None,
        "ResolveStatus": "SkippedNoGraph",
        "ResolveError": None,
        "OwnerSource": "DemoFallbackNoGraph"
    })

owner_resolved_schema = T.StructType([
    T.StructField("OwnerObjectId", T.StringType(), True),
    T.StructField("OwnerName", T.StringType(), True),
    T.StructField("OwnerEmail", T.StringType(), True),
    T.StructField("OwnerUpn", T.StringType(), True),
    T.StructField("ResolveStatus", T.StringType(), True),
    T.StructField("ResolveError", T.StringType(), True),
    T.StructField("OwnerSource", T.StringType(), True),
])

owner_resolved_df = spark.createDataFrame(resolved_rows, schema=owner_resolved_schema)

display(owner_resolved_df)
print("Resolved rows:", owner_resolved_df.count())

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Build dp_dataproduct_owner_contact_current

# CELL ********************

from pyspark.sql import functions as F, types as T
from datetime import datetime, timezone

# =========================
# CONFIG
# =========================
DATA_PRODUCT_OWNER_PATH = "Files/purview_meta_data/DomainModel/DataProductOwner"
OWNER_CONTACT_TABLE = "dp_dataproduct_owner_contact_current"

# Demo fallback (until Graph resolution is added)
OWNER_EMAIL_DEMO_FALLBACK = "<owner_email>"   # <-- CHANGE THIS
OWNER_NAME_DEMO_FALLBACK  = "Demo Owner"

# =========================
# LOAD SSA DataProductOwner
# =========================
dpo_raw = spark.read.format("delta").load(DATA_PRODUCT_OWNER_PATH)

print("Raw DataProductOwner rows:", dpo_raw.count())
display(dpo_raw.limit(20))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Build clean 1:1 mapping (DataProductId -> OwnerObjectId)

# CELL ********************

# =========================
# CLEAN OWNER MAPPING (1:1 assumed)
# =========================
dpo = (
    dpo_raw
    .select(
        F.lower(F.trim(F.col("DataProductId"))).alias("DataProductId"),
        F.trim(F.col("DataProductOwnerId")).alias("OwnerObjectId")
    )
    .filter(F.col("DataProductId").isNotNull() & (F.col("DataProductId") != ""))
    .filter(F.col("OwnerObjectId").isNotNull() & (F.col("OwnerObjectId") != ""))
    .dropDuplicates(["DataProductId"])   # per your 1:1 assumption
)

print("Clean owner mapping rows:", dpo.count())
display(dpo.limit(20))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Create fallback owner resolution table (no Graph for now)

# CELL ********************

# =========================
# DEMO FALLBACK OWNER RESOLUTION (NO GRAPH)
# =========================
owner_ids = [r["OwnerObjectId"] for r in dpo.select("OwnerObjectId").dropDuplicates().collect()]
print("Distinct owner object IDs:", len(owner_ids))

resolved_rows = []
for oid in owner_ids:
    resolved_rows.append({
        "OwnerObjectId": oid,
        "OwnerName": OWNER_NAME_DEMO_FALLBACK,
        "OwnerEmail": OWNER_EMAIL_DEMO_FALLBACK,
        "OwnerUpn": None,
        "ResolveStatus": "SkippedNoGraph",
        "ResolveError": None,
        "OwnerSource": "DemoFallbackNoGraph"
    })

owner_resolved_schema = T.StructType([
    T.StructField("OwnerObjectId", T.StringType(), True),
    T.StructField("OwnerName", T.StringType(), True),
    T.StructField("OwnerEmail", T.StringType(), True),
    T.StructField("OwnerUpn", T.StringType(), True),
    T.StructField("ResolveStatus", T.StringType(), True),
    T.StructField("ResolveError", T.StringType(), True),
    T.StructField("OwnerSource", T.StringType(), True),
])

owner_resolved_df = spark.createDataFrame(resolved_rows, schema=owner_resolved_schema)

print("Resolved owner rows:", owner_resolved_df.count())
display(owner_resolved_df)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Join back to DataProductId and shape final current table

# CELL ********************

# =========================
# BUILD dp_dataproduct_owner_contact_current
# =========================
snapshot_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

dp_owner_contact_current = (
    dpo.alias("dpo")
    .join(owner_resolved_df.alias("r"), on="OwnerObjectId", how="left")
    .select(
        F.col("dpo.DataProductId").alias("DataProductId"),
        F.col("dpo.OwnerObjectId").alias("OwnerObjectId"),
        F.coalesce(F.col("r.OwnerName"), F.lit(OWNER_NAME_DEMO_FALLBACK)).alias("OwnerName"),
        F.coalesce(F.col("r.OwnerEmail"), F.lit(OWNER_EMAIL_DEMO_FALLBACK)).alias("OwnerEmail"),
        F.coalesce(F.col("r.OwnerSource"), F.lit("DemoFallbackJoin")).alias("OwnerSource"),
        F.col("r.ResolveStatus").alias("ResolveStatus"),
        F.col("r.ResolveError").alias("ResolveError"),
        F.lit(snapshot_utc).alias("SnapshotUtc")
    )
)

print("Final owner contact rows:", dp_owner_contact_current.count())
display(dp_owner_contact_current.limit(50))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Save the table to Lakehouse

# CELL ********************

# =========================
# SAVE TABLE
# =========================
(
    dp_owner_contact_current
    .write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(OWNER_CONTACT_TABLE)
)

print(f"Saved table: {OWNER_CONTACT_TABLE}")
display(spark.table(OWNER_CONTACT_TABLE).limit(50))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Validation checks (important)

# CELL ********************

# =========================
# VALIDATION
# =========================
owner_tbl = spark.table(OWNER_CONTACT_TABLE)

print("Total rows:", owner_tbl.count())
print("Distinct DataProductId:", owner_tbl.select("DataProductId").distinct().count())
print("Distinct OwnerObjectId:", owner_tbl.select("OwnerObjectId").distinct().count())

print("OwnerSource breakdown:")
display(owner_tbl.groupBy("OwnerSource").count().orderBy(F.desc("count")))

print("ResolveStatus breakdown:")
display(owner_tbl.groupBy("ResolveStatus").count().orderBy(F.desc("count")))

print("Missing OwnerEmail count (should be 0):")
display(
    owner_tbl.select(
        F.sum(F.when(F.col("OwnerEmail").isNull() | (F.trim(F.col("OwnerEmail")) == ""), 1).otherwise(0)).alias("OwnerEmailMissing")
    )
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# #### Build dp_dataproduct_cccompliance_investigate_current

# MARKDOWN ********************

# Config + table checks

# CELL ********************

from pyspark.sql import functions as F, types as T

# =========================
# CONFIG
# =========================
CC_CURRENT_TABLE = "dp_dataproduct_cccompliance_current"
OWNER_CONTACT_TABLE = "dp_dataproduct_owner_contact_current"
DP_META_TABLE = "dp_dataproductresidency_gold"   # for display name / description
INVESTIGATE_CURRENT_TABLE = "dp_dataproduct_cccompliance_investigate_current"

SUGGESTED_TAG_KEY = "compliance-status"
SUGGESTED_TAG_VALUE = "investigate"

for t in [CC_CURRENT_TABLE, OWNER_CONTACT_TABLE, DP_META_TABLE]:
    print(f"{t}: {'FOUND' if spark.catalog.tableExists(t) else 'MISSING'}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Load source tables

# CELL ********************

cc_cur = spark.table(CC_CURRENT_TABLE)
owner_cur = spark.table(OWNER_CONTACT_TABLE)
dp_meta_src = spark.table(DP_META_TABLE)

print("cc_cur rows:", cc_cur.count())
print("owner_cur rows:", owner_cur.count())
print("dp_meta rows:", dp_meta_src.count())

display(cc_cur.limit(10))
display(owner_cur.limit(10))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Prepare metadata table (display name + description)

# CELL ********************

dp_meta = (
    dp_meta_src
    .select(
        F.lower(F.trim(F.col("DataProductID"))).alias("DataProductId"),
        F.col("DataProductDisplayName").cast("string").alias("MetaDisplayName"),
        F.col("DataProductDescription").cast("string").alias("DataProductDescription")
    )
    .dropDuplicates(["DataProductId"])
)

display(dp_meta.limit(20))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Shape CC current table for investigate logic

# CELL ********************

cc_base = (
    cc_cur
    .select(
        F.lower(F.trim(F.col("DataProductId"))).alias("DataProductId"),
        F.col("SnapshotUtc").cast("string").alias("SnapshotUtc"),
        F.col("DataProductDisplayName").cast("string").alias("CCDisplayName"),
        F.col("HasFullNameClassification").cast("int").alias("HasFullNameClassification"),
        F.col("FullNameColumnCount").cast("int").alias("FullNameColumnCount"),
        F.col("CCForPIIScore").cast("int").alias("CCScorePct"),
        F.col("CCForPIIStatus").cast("string").alias("CCState"),
        F.col("Reason").cast("string").alias("CCReason"),
        F.col("ResourceId").cast("string").alias("ResourceId"),
        F.col("ResourceType").cast("string").alias("ResourceType"),
        F.col("SubscriptionId").cast("string").alias("SubscriptionId"),
        F.col("ResourceGroup").cast("string").alias("ResourceGroup"),
        F.col("Location").cast("string").alias("Location"),
        F.col("VmSize").cast("string").alias("VmSizeCompat"),      # Azure VM size OR Arc model (compat)
        F.col("SecurityType").cast("string").alias("SecurityType"),
        F.col("IsApprovedSku").cast("boolean").alias("IsApprovedSku"),
    )
    .withColumn("HasFullNameClassification", F.coalesce(F.col("HasFullNameClassification"), F.lit(0)))
    .withColumn("FullNameColumnCount", F.coalesce(F.col("FullNameColumnCount"), F.lit(0)))
    .withColumn("ResourceFound", F.col("ResourceId").isNotNull() & (F.trim(F.col("ResourceId")) != ""))
    .withColumn("ResourceType_lc", F.lower(F.trim(F.col("ResourceType"))))
.withColumn(
    "ccApplicableResource",
    F.col("resourceType_lc").isin(
        "microsoft.compute/virtualmachines",
        "microsoft.hybridcompute/machines",
        "microsoft.sqlvirtualmachine/sqlvirtualmachines"
    )
)
    .withColumn("PIIApplicable", F.col("HasFullNameClassification") == F.lit(1))
    .withColumn("CCApplicable", F.col("CCApplicableResource") & F.col("PIIApplicable"))
    .withColumn(
        "ResourceName",
        F.when(F.col("ResourceId").isNotNull(), F.element_at(F.split(F.col("ResourceId"), "/"), -1))
         .otherwise(F.lit(None).cast("string"))
    )
    # Optional explainability (derived safely from current table where possible)
    .withColumn("LookupSkuOrModel", F.col("VmSizeCompat"))
    .withColumn(
    "CCResourceKind",
    F.when(F.col("ResourceType_lc") == "microsoft.compute/virtualmachines", F.lit("AzureVM"))
     .when(F.col("ResourceType_lc") == "microsoft.hybridcompute/machines", F.lit("ArcMachine"))
     .when(F.col("ResourceType_lc") == "microsoft.sqlvirtualmachine/sqlvirtualmachines", F.lit("SqlVirtualMachine"))
     .otherwise(F.lit(None).cast("string"))
)
    .withColumn("ArcCloudProvider", F.lit(None).cast("string"))  # will populate later when available in persisted schema
    .withColumn("ArcStatus", F.lit(None).cast("string"))         # will populate later when available in persisted schema
)

display(cc_base.limit(20))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Join owner + metadata and compute investigation flags

# CELL ********************

owner_base = (
    owner_cur
    .select(
        F.lower(F.trim(F.col("DataProductId"))).alias("DataProductId"),
        F.col("OwnerObjectId").cast("string").alias("OwnerObjectId"),
        F.col("OwnerName").cast("string").alias("OwnerName"),
        F.col("OwnerEmail").cast("string").alias("OwnerEmail"),
        F.col("OwnerSource").cast("string").alias("OwnerSource"),
        F.col("ResolveStatus").cast("string").alias("OwnerResolveStatus"),
    )
    .dropDuplicates(["DataProductId"])
)

inv_joined = (
    cc_base.alias("cc")
    .join(owner_base.alias("own"), on="DataProductId", how="left")
    .join(dp_meta.alias("meta"), on="DataProductId", how="left")
    .withColumn(
        "DataProductDisplayName",
        F.coalesce(F.col("cc.CCDisplayName"), F.col("meta.MetaDisplayName"))
    )
    .withColumn(
        "InvestigationRequired",
        (F.col("cc.CCApplicable") == F.lit(True)) &
        (F.col("cc.CCScorePct").isin([50, 75]))
    )
    .withColumn(
        "InvestigationReasonCode",
        F.when(F.col("InvestigationRequired") == F.lit(False), F.lit(None).cast("string"))
         .when(F.col("cc.CCScorePct") == F.lit(50), F.lit("CC_NOT_CONFIDENTIAL_OR_MODEL_MISSING"))
         .when(F.col("cc.CCScorePct") == F.lit(75), F.lit("CC_CONFIDENTIAL_BUT_NOT_APPROVED"))
         .otherwise(F.lit("CC_REVIEW_REQUIRED"))
    )
    .withColumn("SuggestedTagKey", F.lit(SUGGESTED_TAG_KEY))
    .withColumn("SuggestedTagValue", F.lit(SUGGESTED_TAG_VALUE))
)

display(inv_joined.limit(20))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Filter to investigation candidates and shape final table

# CELL ********************

investigate_current_df = (
    inv_joined
    .filter(F.col("InvestigationRequired") == F.lit(True))
    .select(
        # Time / audit
        F.col("cc.SnapshotUtc").alias("SnapshotUtc"),

        # Data product identity
        F.col("DataProductId").cast("string").alias("DataProductId"),
        F.col("DataProductDisplayName").cast("string").alias("DataProductDisplayName"),
        F.col("meta.DataProductDescription").cast("string").alias("DataProductDescription"),

        # CC scoring
        F.col("cc.CCScorePct").cast("int").alias("CCScorePct"),
        F.col("cc.CCState").cast("string").alias("CCState"),
        F.col("cc.CCReason").cast("string").alias("CCReason"),

        # Investigation flags
        F.col("InvestigationRequired").cast("boolean").alias("InvestigationRequired"),
        F.col("InvestigationReasonCode").cast("string").alias("InvestigationReasonCode"),

        # Resource targeting
        F.col("cc.ResourceFound").cast("boolean").alias("ResourceFound"),
        F.col("cc.CCApplicableResource").cast("boolean").alias("CCApplicableResource"),
        F.col("cc.CCApplicable").cast("boolean").alias("CCApplicable"),
        F.col("cc.ResourceId").cast("string").alias("ResourceId"),
        F.col("cc.ResourceName").cast("string").alias("ResourceName"),
        F.col("cc.ResourceType").cast("string").alias("ResourceType"),
        F.col("cc.SubscriptionId").cast("string").alias("SubscriptionId"),
        F.col("cc.ResourceGroup").cast("string").alias("ResourceGroup"),
        F.col("cc.Location").cast("string").alias("Location"),

        # PII/full-name context
        F.col("cc.HasFullNameClassification").cast("int").alias("HasFullNameClassification"),
        F.col("cc.FullNameColumnCount").cast("int").alias("FullNameColumnCount"),

        # Owner / notification
        F.col("own.OwnerObjectId").cast("string").alias("OwnerObjectId"),
        F.col("own.OwnerName").cast("string").alias("OwnerName"),
        F.col("own.OwnerEmail").cast("string").alias("OwnerEmail"),
        F.col("own.OwnerSource").cast("string").alias("OwnerSource"),
        F.col("own.OwnerResolveStatus").cast("string").alias("OwnerResolveStatus"),

        # Tag defaults
        F.col("SuggestedTagKey").cast("string").alias("SuggestedTagKey"),
        F.col("SuggestedTagValue").cast("string").alias("SuggestedTagValue"),

        # Optional explainability (included)
        F.col("cc.LookupSkuOrModel").cast("string").alias("LookupSkuOrModel"),
        F.col("cc.IsApprovedSku").cast("boolean").alias("IsApprovedSku"),
        F.col("cc.CCResourceKind").cast("string").alias("CCResourceKind"),
        F.col("cc.ArcCloudProvider").cast("string").alias("ArcCloudProvider"),
        F.col("cc.ArcStatus").cast("string").alias("ArcStatus"),

        # Compatibility/debug (helpful for first demos)
        F.col("cc.VmSizeCompat").cast("string").alias("VmSizeCompat"),
        F.col("cc.SecurityType").cast("string").alias("SecurityType"),
    )
    .dropDuplicates(["DataProductId"])  # current queue assumption
)

print("Investigation candidate rows:", investigate_current_df.count())
display(investigate_current_df)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Save the table

# CELL ********************

(
    investigate_current_df
    .write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(INVESTIGATE_CURRENT_TABLE)
)

print(f"Saved table: {INVESTIGATE_CURRENT_TABLE}")
display(spark.table(INVESTIGATE_CURRENT_TABLE).limit(50))

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# Validate (important)

# CELL ********************

inv_tbl = spark.table(INVESTIGATE_CURRENT_TABLE)

print("Total rows:", inv_tbl.count())

print("Score breakdown (should only be 50/75):")
display(inv_tbl.groupBy("CCScorePct").count().orderBy("CCScorePct"))

print("CCResourceKind breakdown:")
display(inv_tbl.groupBy("CCResourceKind").count().orderBy(F.desc("count")))

print("OwnerSource breakdown:")
display(inv_tbl.groupBy("OwnerSource").count().orderBy(F.desc("count")))

print("Missing owner email count (should be 0 with fallback):")
display(
    inv_tbl.select(
        F.sum(F.when(F.col("OwnerEmail").isNull() | (F.trim(F.col("OwnerEmail")) == ""), 1).otherwise(0)).alias("OwnerEmailMissing")
    )
)

print("Preview action payload columns:")
display(
    inv_tbl.select(
        "DataProductDisplayName",
        "DataProductId",
        "CCScorePct",
        "CCReason",
        "LookupSkuOrModel",
        "ResourceType",
        "ResourceId",
        "OwnerEmail",
        "SuggestedTagKey",
        "SuggestedTagValue"
    ).limit(20)
)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ### Defender scorecard (FULL DP list; Fabric/S3 → N/A=100) + quick validation

# CELL ********************

# =========================================
# DEFENDER CHECK SCORECARD (FULL DP list -> exact current/history schemas)
# =========================================

from pyspark.sql import functions as F
from pyspark.sql import types as T

# ---- 1) Evaluate Defender only for applicable DPs (performance), but output includes ALL DPs ----
def_eval_ids = [
    r["DataProductId"]
    for r in dp_base.filter(F.col("DefenderApplicable") == F.lit(True))
                    .select("DataProductId")
                    .distinct()
                    .collect()
]
print("Defender evaluation dp count:", len(def_eval_ids))

def_rows = []
if len(def_eval_ids) > 0:
    def_results = post_batched(ROUTES["defender"], def_eval_ids)

    for r in (def_results or []):
        dp = str(r.get("dataProductId") or "").strip().lower()
        if not dp:
            continue

        roll = r.get("rollup") or {}
        if not isinstance(roll, dict):
            roll = {}

        # Some implementations may return these either top-level or under rollup
        applicable_resource_count = r.get("applicableResourceCount")
        configured_resource_count = r.get("configuredResourceCount")
        running_resource_count = r.get("runningResourceCount")
        high_active_alert_count = r.get("highActiveAlertCount")
        has_unhealthy_assessments = r.get("hasUnhealthyAssessments")

        if applicable_resource_count is None:
            applicable_resource_count = roll.get("applicableResourceCount")
        if configured_resource_count is None:
            configured_resource_count = roll.get("configuredResourceCount")
        if running_resource_count is None:
            running_resource_count = roll.get("runningResourceCount")
        if high_active_alert_count is None:
            high_active_alert_count = roll.get("highActiveAlertCount")
        if has_unhealthy_assessments is None:
            has_unhealthy_assessments = roll.get("hasUnhealthyAssessments")

        def_rows.append({
            "dataProductId": dp,
            "resourceFound": (bool(r.get("resourceFound")) if r.get("resourceFound") is not None else None),
            "applicable": (bool(r.get("applicable")) if r.get("applicable") is not None else None),

            # Keep API-returned score/state for debugging/audit.
            # Fabric will recompute the final score/state below from evidence columns.
            "progressScore": (int(r.get("progressScore")) if r.get("progressScore") is not None else None),
            "progressState": r.get("progressState"),

            "applicableResourceCount": int(applicable_resource_count or 0),
            "configuredResourceCount": int(configured_resource_count or 0),
            "runningResourceCount": int(running_resource_count or 0),
            "highActiveAlertCount": int(high_active_alert_count or 0),
            "hasUnhealthyAssessments": (
                bool(has_unhealthy_assessments) if has_unhealthy_assessments is not None else None
            ),

            # Persist raw JSON payloads for audit/debug (exact schema columns)
            "resourcesJson": json.dumps(r.get("resources", []))[:200000],
            "evaluatedResourcesJson": json.dumps(r.get("evaluatedResources", []))[:200000],
            "detailsJson": json.dumps(r.get("details", {}))[:200000],
        })

def_api_schema = T.StructType([
    T.StructField("dataProductId", T.StringType(), False),
    T.StructField("resourceFound", T.BooleanType(), True),
    T.StructField("applicable", T.BooleanType(), True),
    T.StructField("progressScore", T.IntegerType(), True),
    T.StructField("progressState", T.StringType(), True),
    T.StructField("applicableResourceCount", T.IntegerType(), True),
    T.StructField("configuredResourceCount", T.IntegerType(), True),
    T.StructField("runningResourceCount", T.IntegerType(), True),
    T.StructField("highActiveAlertCount", T.IntegerType(), True),
    T.StructField("hasUnhealthyAssessments", T.BooleanType(), True),
    T.StructField("resourcesJson", T.StringType(), True),
    T.StructField("evaluatedResourcesJson", T.StringType(), True),
    T.StructField("detailsJson", T.StringType(), True),
])

if def_rows:
    def_api = spark.createDataFrame(def_rows, schema=def_api_schema).dropDuplicates(["dataProductId"])
else:
    def_api = spark.createDataFrame([], def_api_schema)

# ---- 2) Join to FULL DP list (scorecard must include all DPs) ----
# IMPORTANT: preserve base DataProductId explicitly (avoid drop() on case-variant key names)
b = dp_base.select("DataProductId", "DefenderApplicable").alias("b")
a = def_api.alias("a")

def_base = (
    b.join(a, F.col("b.DataProductId") == F.col("a.dataProductId"), how="left")
     .select(
         F.col("b.DataProductId").alias("dataProductId"),
         F.col("b.DefenderApplicable").alias("DefenderApplicable"),
         F.col("a.resourceFound").alias("resourceFound"),
         F.col("a.applicable").alias("applicable"),
         F.col("a.progressScore").alias("apiProgressScore"),
         F.col("a.progressState").alias("apiProgressState"),
         F.col("a.applicableResourceCount").alias("applicableResourceCount"),
         F.col("a.configuredResourceCount").alias("configuredResourceCount"),
         F.col("a.runningResourceCount").alias("runningResourceCount"),
         F.col("a.highActiveAlertCount").alias("highActiveAlertCount"),
         F.col("a.hasUnhealthyAssessments").alias("hasUnhealthyAssessments"),
         F.col("a.resourcesJson").alias("resourcesJson"),
         F.col("a.evaluatedResourcesJson").alias("evaluatedResourcesJson"),
         F.col("a.detailsJson").alias("detailsJson"),
     )
     .withColumn("snapshotUtc", F.current_timestamp())
)

# ---- 3) Final Defender scoring in Fabric (guardrail over API output) ----
# Final rubric enforced here:
# - DefenderApplicable = false => N/A => 100
# - resourceFound = false => 0
# - applicable = false => notApplicable => 100
# - configuredResourceCount = 0 => 25
# - hasUnhealthyAssessments = true => 50
# - runningResourceCount = 0 => 50 (configured but not yet running / no assessments)
# - highActiveAlertCount > 0 => 75
# - else => 100
#
# This keeps Fabric as the final scoring authority even if the function app returns a stale score.
def_scored = (
    def_base
    .withColumn(
        "resourceFound",
        F.when(F.col("DefenderApplicable") == F.lit(False), F.lit(False))
         .otherwise(F.coalesce(F.col("resourceFound"), F.lit(False)))
         .cast("boolean")
    )
    .withColumn(
        "applicable",
        F.when(F.col("DefenderApplicable") == F.lit(False), F.lit(False))
         .otherwise(F.coalesce(F.col("applicable"), F.lit(True)))
         .cast("boolean")
    )
    .withColumn("applicableResourceCount", F.coalesce(F.col("applicableResourceCount"), F.lit(0)).cast("int"))
    .withColumn("configuredResourceCount", F.coalesce(F.col("configuredResourceCount"), F.lit(0)).cast("int"))
    .withColumn("runningResourceCount", F.coalesce(F.col("runningResourceCount"), F.lit(0)).cast("int"))
    .withColumn("highActiveAlertCount", F.coalesce(F.col("highActiveAlertCount"), F.lit(0)).cast("int"))
    .withColumn(
        "hasUnhealthyAssessments",
        F.when(F.col("DefenderApplicable") == F.lit(False), F.lit(False))
         .otherwise(F.coalesce(F.col("hasUnhealthyAssessments"), F.lit(False)))
         .cast("boolean")
    )
    .withColumn(
        "progressScore",
        F.when(F.col("DefenderApplicable") == F.lit(False), F.lit(100))
         .when(F.col("resourceFound") == F.lit(False), F.lit(0))
         .when(F.col("applicable") == F.lit(False), F.lit(100))
         .when(F.col("configuredResourceCount") <= F.lit(0), F.lit(25))
         .when(F.col("hasUnhealthyAssessments") == F.lit(True), F.lit(50))
         .when(F.col("runningResourceCount") <= F.lit(0), F.lit(50))
         .when(F.col("highActiveAlertCount") > F.lit(0), F.lit(75))
         .otherwise(F.lit(100))
         .cast("int")
    )
    .withColumn(
        "progressState",
        F.when(F.col("DefenderApplicable") == F.lit(False), F.lit("NA_NotApplicable"))
         .when(F.col("resourceFound") == F.lit(False), F.lit("NotFound"))
         .when(F.col("applicable") == F.lit(False), F.lit("notApplicable"))
         .when(F.col("configuredResourceCount") <= F.lit(0), F.lit("notConfigured"))
         .when(F.col("hasUnhealthyAssessments") == F.lit(True), F.lit("runningUnhealthy"))
         .when(F.col("runningResourceCount") <= F.lit(0), F.lit("configuredNotRunning"))
         .when(F.col("highActiveAlertCount") > F.lit(0), F.lit("runningHealthyWithActiveAlert"))
         .otherwise(F.lit("runningHealthy"))
         .cast("string")
    )
    .withColumn(
        "resourcesJson",
        F.when(F.col("resourcesJson").isNull(), F.lit("[]"))
         .otherwise(F.col("resourcesJson"))
         .cast("string")
    )
    .withColumn(
        "evaluatedResourcesJson",
        F.when(F.col("evaluatedResourcesJson").isNull(), F.lit("[]"))
         .otherwise(F.col("evaluatedResourcesJson"))
         .cast("string")
    )
    .withColumn(
        "detailsJson",
        F.when(
            F.col("detailsJson").isNull() & (F.col("DefenderApplicable") == F.lit(False)),
            F.lit(json.dumps({"note": "Defender not applicable for this data product. N/A treated as compliant (100%)."}))
        )
         .when(
            F.col("detailsJson").isNull(),
            F.lit(json.dumps({"note": "No Defender API result returned for applicable data product; final rubric applied in Fabric."}))
        )
         .otherwise(F.col("detailsJson"))
         .cast("string")
    )
)

# ---- 4) Shape EXACT current/history schema (same schema for both defender tables) ----
def_current_df = def_scored.select(
    F.col("dataProductId").cast("string").alias("dataProductId"),
    F.col("snapshotUtc").alias("snapshotUtc"),
    F.col("resourceFound").cast("boolean").alias("resourceFound"),
    F.col("applicable").cast("boolean").alias("applicable"),
    F.col("progressScore").cast("int").alias("progressScore"),
    F.col("progressState").cast("string").alias("progressState"),
    F.col("applicableResourceCount").cast("int").alias("applicableResourceCount"),
    F.col("configuredResourceCount").cast("int").alias("configuredResourceCount"),
    F.col("runningResourceCount").cast("int").alias("runningResourceCount"),
    F.col("highActiveAlertCount").cast("int").alias("highActiveAlertCount"),
    F.col("hasUnhealthyAssessments").cast("boolean").alias("hasUnhealthyAssessments"),
    F.col("resourcesJson").cast("string").alias("resourcesJson"),
    F.col("evaluatedResourcesJson").cast("string").alias("evaluatedResourcesJson"),
    F.col("detailsJson").cast("string").alias("detailsJson"),
)

def_expected = [
    "dataProductId",
    "snapshotUtc",
    "resourceFound",
    "applicable",
    "progressScore",
    "progressState",
    "applicableResourceCount",
    "configuredResourceCount",
    "runningResourceCount",
    "highActiveAlertCount",
    "hasUnhealthyAssessments",
    "resourcesJson",
    "evaluatedResourcesJson",
    "detailsJson",
]

assert_exact_columns(def_current_df, def_expected, "DEFENDER CURRENT")

# history table has same schema in your environment
def_history_df = def_current_df.select(*def_expected)
assert_exact_columns(def_history_df, def_expected, "DEFENDER HISTORY")

# ---- 5) Write current + history using exact-schema helper ----
write_current_and_history_exact(def_current_df, DEF_CURRENT, def_history_df, DEF_HISTORY)
print(f"Wrote DEFENDER current+history -> {DEF_CURRENT}, {DEF_HISTORY}")

# -------------------
# Quick validation: all DPs present?
# -------------------
print("Row counts (should match base DP count):")
base_cnt = dp_base.select("DataProductId").distinct().count()
print("Base DP:", base_cnt)
print("Tag:", spark.table(TAG_CURRENT).count())
print("Residency:", spark.table(RES_CURRENT).count())
print("CC:", spark.table(CC_CURRENT).count())
print("Defender:", spark.table(DEF_CURRENT).count())

print("\nSample view (Defender table schema):")
spark.table(DEF_CURRENT).select(
    "dataProductId",
    "progressScore",
    "progressState",
    "resourceFound",
    "applicable",
    "configuredResourceCount",
    "runningResourceCount",
    "highActiveAlertCount",
    "hasUnhealthyAssessments"
).show(50, truncate=False)


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# MAGIC %%sql
# MAGIC WITH latest_snapshot AS (
# MAGIC     SELECT MAX(SnapshotTimeUtc) AS SnapshotTimeUtc
# MAGIC     FROM dp_dataproduct_residencycompliance_current
# MAGIC ),
# MAGIC 
# MAGIC base AS (
# MAGIC     SELECT
# MAGIC         c.SnapshotTimeUtc,
# MAGIC         c.DataProductID,
# MAGIC         c.DataProductDisplayName,
# MAGIC         c.DataProductDescription,
# MAGIC 
# MAGIC         c.GlossaryResidencyRegionName,
# MAGIC         LOWER(TRIM(c.GlossaryResidencyRegionCode)) AS GlossaryResidencyRegionCode,
# MAGIC         c.GlossaryResidencyMissing,        -- BOOLEAN
# MAGIC 
# MAGIC         c.AzureResourceFound,              -- BOOLEAN
# MAGIC         c.AzureResourceCount,
# MAGIC         LOWER(TRIM(c.AzureLocations)) AS AzureResidencyCode,
# MAGIC         c.AzureResourceIds,
# MAGIC         c.AzureLocationMatch,              -- BOOLEAN
# MAGIC 
# MAGIC         c.ResidencyScorePct,
# MAGIC         c.ResidencyScoreReason
# MAGIC     FROM dp_dataproduct_residencycompliance_current c
# MAGIC     INNER JOIN latest_snapshot l
# MAGIC         ON c.SnapshotTimeUtc = l.SnapshotTimeUtc
# MAGIC ),
# MAGIC 
# MAGIC approved_regions AS (
# MAGIC     SELECT
# MAGIC         LOWER(TRIM(region_code)) AS region_code,
# MAGIC         COALESCE(CAST(approved AS BOOLEAN), false) AS is_approved
# MAGIC     FROM rs_approved_regions
# MAGIC )
# MAGIC 
# MAGIC SELECT
# MAGIC     b.SnapshotTimeUtc,
# MAGIC     b.DataProductID,
# MAGIC     b.DataProductDisplayName,
# MAGIC     b.DataProductDescription,
# MAGIC 
# MAGIC     b.GlossaryResidencyRegionName,
# MAGIC     b.GlossaryResidencyRegionCode,
# MAGIC     b.GlossaryResidencyMissing,
# MAGIC 
# MAGIC     b.AzureResourceFound,
# MAGIC     b.AzureResourceCount,
# MAGIC     b.AzureResidencyCode,
# MAGIC     b.AzureResourceIds,
# MAGIC     b.AzureLocationMatch,
# MAGIC 
# MAGIC     b.ResidencyScorePct,
# MAGIC     b.ResidencyScoreReason,
# MAGIC 
# MAGIC     COALESCE(ar.is_approved, false) AS IsAzureRegionApproved,
# MAGIC 
# MAGIC     b.AzureResidencyCode AS targetResidencyCode,
# MAGIC     b.GlossaryResidencyRegionCode AS expectedCurrentResidencyCode
# MAGIC 
# MAGIC FROM base b
# MAGIC LEFT JOIN approved_regions ar
# MAGIC     ON b.AzureResidencyCode = ar.region_code
# MAGIC 
# MAGIC WHERE
# MAGIC     COALESCE(b.AzureResourceFound, false) = true
# MAGIC     AND COALESCE(b.AzureResourceCount, 0) >= 1
# MAGIC     AND b.AzureResidencyCode IS NOT NULL
# MAGIC     AND b.AzureResidencyCode <> ''
# MAGIC     AND INSTR(b.AzureResidencyCode, ',') = 0
# MAGIC     AND COALESCE(ar.is_approved, false) = true
# MAGIC     AND (
# MAGIC         COALESCE(b.GlossaryResidencyMissing, false) = true
# MAGIC         OR COALESCE(b.GlossaryResidencyRegionCode, '') <> b.AzureResidencyCode
# MAGIC     )
# MAGIC 
# MAGIC ORDER BY b.DataProductDisplayName;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ### Table to hold Eligibility for Purview residency change for Copilot to recommend

# MARKDOWN ********************

# dp_copilot_purview_residency_change_eligibility will contain one row per data product (latest residency snapshot) with:
# 
# current Purview residency (from compliance_current)
# 
# detected Azure residency
# 
# approved-region check
# 
# final boolean: EligibleForResidencyUpdate
# 
# human-readable EligibilityReason
# 
# values Copilot should pass to Preview/Apply:
# 
# TargetResidencyCode
# 
# ExpectedCurrentResidencyCode
# 
# This makes Copilot’s gating deterministic and tool-friendly.

# CELL ********************

# MAGIC %%sql
# MAGIC CREATE OR REPLACE TABLE dp_copilot_purview_residency_change_eligibility
# MAGIC USING DELTA
# MAGIC AS
# MAGIC 
# MAGIC WITH latest_snapshot AS (
# MAGIC     SELECT MAX(SnapshotTimeUtc) AS SnapshotTimeUtc
# MAGIC     FROM dp_dataproduct_residencycompliance_current
# MAGIC ),
# MAGIC 
# MAGIC -- Latest residency compliance snapshot (source of truth for gating)
# MAGIC base_raw AS (
# MAGIC     SELECT
# MAGIC         c.SnapshotTimeUtc,
# MAGIC         c.DataProductID,
# MAGIC         c.DataProductDisplayName,
# MAGIC         c.DataProductDescription,
# MAGIC         c.GlossaryResidencyRegionName,
# MAGIC         c.GlossaryResidencyRegionCode,
# MAGIC         c.GlossaryResidencyMissing,
# MAGIC         c.IsApprovedResidency,         -- existing scorecard field (kept for reference)
# MAGIC         c.AzureResourceFound,
# MAGIC         c.AzureResourceCount,
# MAGIC         c.AzureLocations,
# MAGIC         c.AzureResourceIds,
# MAGIC         c.AzureLocationMatch,
# MAGIC         c.ResidencyScorePct,
# MAGIC         c.ResidencyScoreReason
# MAGIC     FROM dp_dataproduct_residencycompliance_current c
# MAGIC     INNER JOIN latest_snapshot l
# MAGIC         ON c.SnapshotTimeUtc = l.SnapshotTimeUtc
# MAGIC ),
# MAGIC 
# MAGIC -- Normalize/cast fields to avoid BOOLEAN vs INT mismatches
# MAGIC base_norm AS (
# MAGIC     SELECT
# MAGIC         SnapshotTimeUtc,
# MAGIC         DataProductID,
# MAGIC         DataProductDisplayName,
# MAGIC         DataProductDescription,
# MAGIC 
# MAGIC         -- Normalize glossary residency
# MAGIC         NULLIF(LOWER(TRIM(CAST(GlossaryResidencyRegionName AS STRING))), '') AS GlossaryResidencyRegionName,
# MAGIC         NULLIF(LOWER(TRIM(CAST(GlossaryResidencyRegionCode AS STRING))), '') AS GlossaryResidencyRegionCode,
# MAGIC 
# MAGIC         -- Robust boolean normalization (works whether source is bool/int/string)
# MAGIC         CASE
# MAGIC             WHEN LOWER(TRIM(CAST(GlossaryResidencyMissing AS STRING))) IN ('true','1','yes','y') THEN TRUE
# MAGIC             ELSE FALSE
# MAGIC         END AS GlossaryResidencyMissing,
# MAGIC 
# MAGIC         CASE
# MAGIC             WHEN LOWER(TRIM(CAST(AzureResourceFound AS STRING))) IN ('true','1','yes','y') THEN TRUE
# MAGIC             ELSE FALSE
# MAGIC         END AS AzureResourceFound,
# MAGIC 
# MAGIC         COALESCE(CAST(AzureResourceCount AS INT), 0) AS AzureResourceCount,
# MAGIC 
# MAGIC         -- Normalize Azure residency detected (from AzureLocations)
# MAGIC         NULLIF(LOWER(TRIM(CAST(AzureLocations AS STRING))), '') AS AzureResidencyCode,
# MAGIC 
# MAGIC         CAST(AzureLocations AS STRING) AS AzureLocationsRaw,
# MAGIC         CAST(AzureResourceIds AS STRING) AS AzureResourceIds,
# MAGIC 
# MAGIC         CASE
# MAGIC             WHEN LOWER(TRIM(CAST(AzureLocationMatch AS STRING))) IN ('true','1','yes','y') THEN TRUE
# MAGIC             ELSE FALSE
# MAGIC         END AS AzureLocationMatch,
# MAGIC 
# MAGIC         COALESCE(CAST(ResidencyScorePct AS INT), 0) AS ResidencyScorePct,
# MAGIC         CAST(ResidencyScoreReason AS STRING) AS ResidencyScoreReason,
# MAGIC 
# MAGIC         -- Keep existing scorecard field for reference/debug (do not use as gate authority)
# MAGIC         CASE
# MAGIC             WHEN LOWER(TRIM(CAST(IsApprovedResidency AS STRING))) IN ('true','1','yes','y') THEN TRUE
# MAGIC             ELSE FALSE
# MAGIC         END AS IsApprovedResidency_ScorecardField
# MAGIC     FROM base_raw
# MAGIC ),
# MAGIC 
# MAGIC -- Approved regions ruleset (authoritative gate list)
# MAGIC approved_regions AS (
# MAGIC     SELECT
# MAGIC         NULLIF(LOWER(TRIM(CAST(region_code AS STRING))), '') AS region_code,
# MAGIC         CASE
# MAGIC             WHEN LOWER(TRIM(CAST(approved AS STRING))) IN ('true','1','yes','y') THEN TRUE
# MAGIC             ELSE FALSE
# MAGIC         END AS approved,
# MAGIC         CAST(region_name AS STRING) AS region_name,
# MAGIC         CAST(notes AS STRING) AS notes
# MAGIC     FROM rs_approved_regions
# MAGIC     WHERE region_code IS NOT NULL
# MAGIC ),
# MAGIC 
# MAGIC joined AS (
# MAGIC     SELECT
# MAGIC         b.*,
# MAGIC         ar.region_code AS ApprovedRegionCodeMatch,
# MAGIC         COALESCE(ar.approved, FALSE) AS IsAzureRegionApproved,
# MAGIC         ar.region_name AS ApprovedRegionName,
# MAGIC         ar.notes AS ApprovedRegionNotes,
# MAGIC 
# MAGIC         -- Single clear Azure value gate (current design: comma indicates multiple)
# MAGIC         CASE
# MAGIC             WHEN b.AzureResidencyCode IS NULL THEN FALSE
# MAGIC             WHEN INSTR(b.AzureResidencyCode, ',') > 0 THEN FALSE
# MAGIC             ELSE TRUE
# MAGIC         END AS HasSingleClearAzureResidencyValue
# MAGIC     FROM base_norm b
# MAGIC     LEFT JOIN approved_regions ar
# MAGIC         ON b.AzureResidencyCode = ar.region_code
# MAGIC )
# MAGIC 
# MAGIC SELECT
# MAGIC     -- Snapshot / processing metadata
# MAGIC     j.SnapshotTimeUtc,
# MAGIC     CURRENT_TIMESTAMP() AS EligibilityComputedAtUtc,
# MAGIC 
# MAGIC     -- Identity / display
# MAGIC     j.DataProductID,
# MAGIC     j.DataProductDisplayName,
# MAGIC     j.DataProductDescription,
# MAGIC 
# MAGIC     -- Current Purview state (as represented in latest compliance snapshot)
# MAGIC     j.GlossaryResidencyRegionName,
# MAGIC     j.GlossaryResidencyRegionCode,
# MAGIC     j.GlossaryResidencyMissing,
# MAGIC 
# MAGIC     -- Azure detected state
# MAGIC     j.AzureResourceFound,
# MAGIC     j.AzureResourceCount,
# MAGIC     j.AzureResidencyCode,
# MAGIC     j.AzureLocationsRaw,
# MAGIC     j.AzureResourceIds,
# MAGIC     j.AzureLocationMatch,
# MAGIC     j.HasSingleClearAzureResidencyValue,
# MAGIC 
# MAGIC     -- Approved region gate (authoritative)
# MAGIC     j.IsAzureRegionApproved,
# MAGIC     j.ApprovedRegionCodeMatch,
# MAGIC     j.ApprovedRegionName,
# MAGIC     j.ApprovedRegionNotes,
# MAGIC 
# MAGIC     -- Existing scorecard context (useful for Copilot explanation / debugging)
# MAGIC     j.ResidencyScorePct,
# MAGIC     j.ResidencyScoreReason,
# MAGIC     j.IsApprovedResidency_ScorecardField,
# MAGIC 
# MAGIC     -- Values Copilot should use for preview/apply
# MAGIC     j.AzureResidencyCode AS TargetResidencyCode,
# MAGIC     j.GlossaryResidencyRegionCode AS ExpectedCurrentResidencyCode,
# MAGIC 
# MAGIC     -- Final deterministic gate for Copilot
# MAGIC     CASE
# MAGIC         WHEN j.AzureResourceFound = TRUE
# MAGIC          AND j.AzureResourceCount >= 1
# MAGIC          AND j.AzureResidencyCode IS NOT NULL
# MAGIC          AND j.HasSingleClearAzureResidencyValue = TRUE
# MAGIC          AND j.IsAzureRegionApproved = TRUE
# MAGIC          AND (
# MAGIC                 j.GlossaryResidencyMissing = TRUE
# MAGIC                 OR COALESCE(j.GlossaryResidencyRegionCode, '') <> COALESCE(j.AzureResidencyCode, '')
# MAGIC              )
# MAGIC         THEN TRUE
# MAGIC         ELSE FALSE
# MAGIC     END AS EligibleForResidencyUpdate,
# MAGIC 
# MAGIC     -- Deterministic reason for Copilot / semantic model
# MAGIC     CASE
# MAGIC         WHEN j.AzureResourceFound <> TRUE
# MAGIC             THEN 'Azure resource not found for data product'
# MAGIC         WHEN j.AzureResourceCount < 1
# MAGIC             THEN 'No mapped Azure resource found for data product'
# MAGIC         WHEN j.AzureResidencyCode IS NULL
# MAGIC             THEN 'Azure residency not detected'
# MAGIC         WHEN j.HasSingleClearAzureResidencyValue <> TRUE
# MAGIC             THEN 'Multiple Azure residency values detected; manual review required'
# MAGIC         WHEN j.IsAzureRegionApproved <> TRUE
# MAGIC             THEN 'Azure residency is not in approved region list; do not offer Purview update'
# MAGIC         WHEN j.GlossaryResidencyMissing = TRUE
# MAGIC             THEN 'Eligible: Purview residency missing; Azure residency detected and approved'
# MAGIC         WHEN COALESCE(j.GlossaryResidencyRegionCode, '') = COALESCE(j.AzureResidencyCode, '')
# MAGIC             THEN 'Purview residency already matches Azure residency'
# MAGIC         ELSE 'Eligible: Purview residency differs from Azure residency; Azure residency detected and approved'
# MAGIC     END AS EligibilityReason,
# MAGIC 
# MAGIC     -- Action hints for Copilot/UI (optional but useful)
# MAGIC     CASE
# MAGIC         WHEN j.AzureResourceFound = TRUE
# MAGIC          AND j.AzureResourceCount >= 1
# MAGIC          AND j.AzureResidencyCode IS NOT NULL
# MAGIC          AND j.HasSingleClearAzureResidencyValue = TRUE
# MAGIC          AND j.IsAzureRegionApproved = TRUE
# MAGIC          AND j.GlossaryResidencyMissing = TRUE
# MAGIC         THEN 'add'
# MAGIC         WHEN j.AzureResourceFound = TRUE
# MAGIC          AND j.AzureResourceCount >= 1
# MAGIC          AND j.AzureResidencyCode IS NOT NULL
# MAGIC          AND j.HasSingleClearAzureResidencyValue = TRUE
# MAGIC          AND j.IsAzureRegionApproved = TRUE
# MAGIC          AND j.GlossaryResidencyMissing = FALSE
# MAGIC          AND COALESCE(j.GlossaryResidencyRegionCode, '') <> COALESCE(j.AzureResidencyCode, '')
# MAGIC         THEN 'replace'
# MAGIC         ELSE 'none'
# MAGIC     END AS SuggestedPurviewResidencyAction,
# MAGIC 
# MAGIC     -- Simple version stamp so future logic changes are traceable
# MAGIC     'v1' AS EligibilityLogicVersion
# MAGIC 
# MAGIC FROM joined j;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# MAGIC %%sql
# MAGIC SELECT
# MAGIC   MAX(SnapshotTimeUtc) AS SnapshotTimeUtc,
# MAGIC   COUNT(*) AS RowCount,
# MAGIC   SUM(CASE WHEN EligibleForResidencyUpdate THEN 1 ELSE 0 END) AS EligibleCount
# MAGIC FROM dp_copilot_purview_residency_change_eligibility;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# MAGIC %%sql
# MAGIC SELECT
# MAGIC   DataProductDisplayName,
# MAGIC   DataProductID,
# MAGIC   GlossaryResidencyRegionCode,
# MAGIC   TargetResidencyCode,
# MAGIC   ExpectedCurrentResidencyCode,
# MAGIC   IsAzureRegionApproved,
# MAGIC   EligibleForResidencyUpdate,
# MAGIC   SuggestedPurviewResidencyAction,
# MAGIC   EligibilityReason
# MAGIC FROM dp_copilot_purview_residency_change_eligibility
# MAGIC WHERE EligibleForResidencyUpdate = TRUE
# MAGIC ORDER BY DataProductDisplayName;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# MAGIC %%sql
# MAGIC SELECT *
# MAGIC FROM dp_copilot_purview_residency_change_eligibility
# MAGIC WHERE EligibleForResidencyUpdate = 'true';

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# MAGIC %%sql
# MAGIC DROP TABLE IF EXISTS dp_cccompliance_investigate_current;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }

# MARKDOWN ********************

# ### Table to hold Avg Compliance Score across all these areas in a delta table

# MARKDOWN ********************

# We first tried to create a DAX calculated table in the semantic model.
# 
# That failed because the semantic model is Direct Lake, and the calculated table referenced Direct Lake tables.
# 
# So we moved the flattening logic upstream into Fabric and created a proper current-state summary table:
# 
# dp_dataproduct_compliance_summary_current
# 
# This made reporting much simpler and avoided repeated values in Power BI table visuals.

# CELL ********************

# MAGIC %%sql
# MAGIC CREATE OR REPLACE TABLE dp_dataproduct_compliance_summary_current
# MAGIC USING DELTA
# MAGIC AS
# MAGIC 
# MAGIC WITH base_products AS (
# MAGIC     SELECT DISTINCT
# MAGIC         CAST(DataProductID AS STRING)          AS DataProductId,
# MAGIC         DataProductDisplayName                 AS DataProductDisplayName
# MAGIC     FROM dp_dataproductresidency_gold
# MAGIC 
# MAGIC     UNION
# MAGIC 
# MAGIC     SELECT DISTINCT
# MAGIC         CAST(DataProductId AS STRING)          AS DataProductId,
# MAGIC         DataProductDisplayName                 AS DataProductDisplayName
# MAGIC     FROM dp_dataproduct_cccompliance_current
# MAGIC 
# MAGIC     UNION
# MAGIC 
# MAGIC     SELECT DISTINCT
# MAGIC         CAST(dataProductId AS STRING)          AS DataProductId,
# MAGIC         NULL                                   AS DataProductDisplayName
# MAGIC     FROM dp_dataproduct_defendercompliance_current
# MAGIC 
# MAGIC     UNION
# MAGIC 
# MAGIC     SELECT DISTINCT
# MAGIC         CAST(dataProductId AS STRING)          AS DataProductId,
# MAGIC         dataProductDisplayName                 AS DataProductDisplayName
# MAGIC     FROM dp_dataproduct_tagcompliance_current
# MAGIC ),
# MAGIC 
# MAGIC base_products_dedup AS (
# MAGIC     SELECT
# MAGIC         DataProductId,
# MAGIC         MAX(DataProductDisplayName) AS DataProductDisplayName
# MAGIC     FROM base_products
# MAGIC     GROUP BY DataProductId
# MAGIC ),
# MAGIC 
# MAGIC residency AS (
# MAGIC     SELECT
# MAGIC         CAST(DataProductID AS STRING)          AS DataProductId,
# MAGIC         AVG(CAST(ResidencyScorePct AS DOUBLE)) AS ResidencyScorePct
# MAGIC     FROM dp_dataproduct_residencycompliance_current
# MAGIC     GROUP BY DataProductID
# MAGIC ),
# MAGIC 
# MAGIC cc AS (
# MAGIC     SELECT
# MAGIC         CAST(DataProductId AS STRING)          AS DataProductId,
# MAGIC         AVG(CAST(CCForPIIScore AS DOUBLE))     AS CCScorePct
# MAGIC     FROM dp_dataproduct_cccompliance_current
# MAGIC     GROUP BY DataProductId
# MAGIC ),
# MAGIC 
# MAGIC defender AS (
# MAGIC     SELECT
# MAGIC         CAST(dataProductId AS STRING)          AS DataProductId,
# MAGIC         AVG(CAST(progressScore AS DOUBLE))     AS DefenderScorePct
# MAGIC     FROM dp_dataproduct_defendercompliance_current
# MAGIC     GROUP BY dataProductId
# MAGIC ),
# MAGIC 
# MAGIC tagging AS (
# MAGIC     SELECT
# MAGIC         CAST(dataProductId AS STRING)          AS DataProductId,
# MAGIC         AVG(CAST(TagScorePct AS DOUBLE))       AS TagScorePct
# MAGIC     FROM dp_dataproduct_tagcompliance_current
# MAGIC     GROUP BY dataProductId
# MAGIC ),
# MAGIC 
# MAGIC patching AS (
# MAGIC     SELECT
# MAGIC         CAST(DataProductId AS STRING) AS DataProductId,
# MAGIC         AVG(
# MAGIC             CASE
# MAGIC                 WHEN PatchAssessmentStatus = 'NoData' THEN 0.0
# MAGIC                 WHEN PatchAssessmentStatus = 'Assessed' AND COALESCE(PendingUpdatesTotal, 0) > 0 THEN 50.0
# MAGIC                 WHEN PatchAssessmentStatus IS NULL THEN 100.0
# MAGIC                 WHEN PatchAssessmentStatus = 'Assessed' AND COALESCE(PendingUpdatesTotal, 0) = 0 THEN 100.0
# MAGIC                 ELSE 100.0
# MAGIC             END
# MAGIC         ) AS PatchComplianceScorePct
# MAGIC     FROM dp_dataproduct_cccompliance_current
# MAGIC     GROUP BY DataProductId
# MAGIC )
# MAGIC 
# MAGIC SELECT
# MAGIC     b.DataProductId,
# MAGIC     b.DataProductDisplayName,
# MAGIC     CAST(ROUND(r.ResidencyScorePct, 0) AS INT)       AS ResidencyScorePct,
# MAGIC     CAST(ROUND(c.CCScorePct, 0) AS INT)              AS CCScorePct,
# MAGIC     CAST(ROUND(d.DefenderScorePct, 0) AS INT)        AS DefenderScorePct,
# MAGIC     CAST(ROUND(t.TagScorePct, 0) AS INT)             AS TagScorePct,
# MAGIC     CAST(ROUND(p.PatchComplianceScorePct, 0) AS INT) AS PatchComplianceScorePct
# MAGIC FROM base_products_dedup b
# MAGIC LEFT JOIN residency r
# MAGIC     ON b.DataProductId = r.DataProductId
# MAGIC LEFT JOIN cc c
# MAGIC     ON b.DataProductId = c.DataProductId
# MAGIC LEFT JOIN defender d
# MAGIC     ON b.DataProductId = d.DataProductId
# MAGIC LEFT JOIN tagging t
# MAGIC     ON b.DataProductId = t.DataProductId
# MAGIC LEFT JOIN patching p
# MAGIC     ON b.DataProductId = p.DataProductId;

# METADATA ********************

# META {
# META   "language": "sparksql",
# META   "language_group": "synapse_pyspark"
# META }
