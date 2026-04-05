import os
import re
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, date, timezone

import requests
import azure.functions as func
from azure.identity import DefaultAzureCredential, ClientSecretCredential
import boto3
from botocore.exceptions import ClientError

# -----------------------------
# Config (set as App Settings)
# -----------------------------
# Purview Unified Catalog endpoint (example):
#   https://api.purview-service.microsoft.com
PURVIEW_ENDPOINT = os.getenv("PURVIEW_ENDPOINT", "https://api.purview-service.microsoft.com").rstrip("/")

# Purview Unified Catalog REST API version (public preview). Keep configurable.
PURVIEW_API_VERSION = os.getenv("PURVIEW_API_VERSION", "2025-09-15-preview")

# Your residency parent glossary term name (exactly as you created it)
DEFAULT_PARENT_TERM_NAME = os.getenv("RESIDENCY_PARENT_TERM_NAME", "Gl-Region")

# Requests timeout (seconds)
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "30"))

# Azure Resource Graph API config
RESOURCE_GRAPH_API_VERSION = os.getenv("RESOURCE_GRAPH_API_VERSION", "2022-10-01")
RESOURCE_GRAPH_URL = (
    "https://management.azure.com/providers/Microsoft.ResourceGraph/resources"
    f"?api-version={RESOURCE_GRAPH_API_VERSION}"
)

# Optional default subscriptions (comma-separated) so callers don't need to pass every time
# Example: "sub1,sub2"
DEFAULT_SUBSCRIPTIONS = [
    s.strip() for s in os.getenv("AZURE_SUBSCRIPTIONS", "").split(",") if s.strip()
]

# Compliance tag rules (lowercase per your standard)
ALLOWED_RESOURCE_ORIGIN = {"arc", "azure"}
ALLOWED_SOVEREIGNTY_ZONE = {"standard", "comprehensive"}

# GUID validator (Purview DataProductId format)
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


# ----------------------------------------------------------
# Optional cross-tenant ARM auth (non-Lighthouse option)
# Purview remains in tenant A (DefaultAzureCredential / managed identity).
# ARM + Resource Graph can use:
#   - default profile  : tenant A
#   - tenant_b profile : explicit SP creds for tenant B subscriptions
# Configure only if you need cross-tenant ARM reads:
#   ARM_TENANT_B_TENANT_ID
#   ARM_TENANT_B_CLIENT_ID
#   ARM_TENANT_B_CLIENT_SECRET
#   ARM_TENANT_B_SUBSCRIPTIONS   (comma-separated subscription IDs)
# ----------------------------------------------------------
ARM_TENANT_B_TENANT_ID = os.getenv("ARM_TENANT_B_TENANT_ID", "").strip()
ARM_TENANT_B_CLIENT_ID = os.getenv("ARM_TENANT_B_CLIENT_ID", "").strip()
ARM_TENANT_B_CLIENT_SECRET = os.getenv("ARM_TENANT_B_CLIENT_SECRET", "").strip()
ARM_TENANT_B_SUBSCRIPTIONS = {
    s.strip().lower()
    for s in os.getenv("ARM_TENANT_B_SUBSCRIPTIONS", "").split(",")
    if s.strip()
}# ----------------------------------------------------------
# Optional Fabric SQL logging (Copilot change logs)
# If configured, the function app will INSERT action log records into Fabric SQL tables.
#
# Required app settings:
#   FABRIC_SQL_SERVER   (e.g. <workspace>.datawarehouse.fabric.microsoft.com)
#   FABRIC_SQL_DATABASE (e.g. <warehouse_or_lakehouse_sql_db_name>)
#
# Optional:
#   FABRIC_SQL_DRIVER (default: ODBC Driver 18 for SQL Server)
#   FABRIC_SQL_LOGGING_ENABLED (true/false)
#   FABRIC_CHANGELOG_TABLE_PURVIEW (default: dbo.dp_copilot_purview_changelog)
#   FABRIC_CHANGELOG_TABLE_CC      (default: dbo.dp_copilot_cc_changelog)
# ----------------------------------------------------------
FABRIC_SQL_SERVER = os.getenv("FABRIC_SQL_SERVER", "").strip()
FABRIC_SQL_DATABASE = os.getenv("FABRIC_SQL_DATABASE", "").strip()
FABRIC_SQL_DRIVER = os.getenv("FABRIC_SQL_DRIVER", "ODBC Driver 18 for SQL Server").strip()
FABRIC_SQL_LOGGING_ENABLED = os.getenv("FABRIC_SQL_LOGGING_ENABLED", "false").strip().lower() in {"1","true","yes","y"}

FABRIC_CHANGELOG_TABLE_PURVIEW = os.getenv("FABRIC_CHANGELOG_TABLE_PURVIEW", "dbo.dp_copilot_purview_changelog").strip()
FABRIC_CHANGELOG_TABLE_CC = os.getenv("FABRIC_CHANGELOG_TABLE_CC", "dbo.dp_copilot_cc_changelog").strip()

# Defender check config
DEFENDER_PLANS = {
    # keys normalized to lowercase for lookup
    "virtualmachines",
    "sqlservers",
    "sqlservervirtualmachines",
    "storageaccounts",
}

# Treat these resource families as "not applicable / cannot be configured" for Defender (N/A => 100)
NON_APPLICABLE_TYPE_PREFIXES = {
    "microsoft.fabric/",
    "microsoft.powerbi/",
}

# Credentials
# - Purview path uses `credential` (DefaultAzureCredential; MI recommended)
# - ARM/ARG path can use one or two credentials depending on configuration
credential = DefaultAzureCredential()

_ARM_CREDENTIALS: Dict[str, Any] = {"default": credential}
if ARM_TENANT_B_TENANT_ID and ARM_TENANT_B_CLIENT_ID and ARM_TENANT_B_CLIENT_SECRET:
    _ARM_CREDENTIALS["tenant_b"] = ClientSecretCredential(
        tenant_id=ARM_TENANT_B_TENANT_ID,
        client_id=ARM_TENANT_B_CLIENT_ID,
        client_secret=ARM_TENANT_B_CLIENT_SECRET,
    )
    logging.info(
        "Cross-tenant ARM auth enabled for tenant_b profile (%d configured subscriptions).",
        len(ARM_TENANT_B_SUBSCRIPTIONS),
    )
elif any([ARM_TENANT_B_TENANT_ID, ARM_TENANT_B_CLIENT_ID, ARM_TENANT_B_CLIENT_SECRET, ARM_TENANT_B_SUBSCRIPTIONS]):
    logging.warning(
        "ARM tenant_b settings are partially configured. tenant_b ARM profile will be disabled until all secret settings are present."
    )

# Keep ANONYMOUS at app-level; EasyAuth handles authentication at the platform layer.
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# -----------------------------
# Helpers
# -----------------------------
def normalize_residency(value: Any) -> str:
    """
    Always return a safe residency string so downstream callers (Custom Connector / Copilot)
    never get null/empty values.
    """
    if value is None:
        return "Unknown (not assigned)"
    if isinstance(value, str) and value.strip() == "":
        return "Unknown (not assigned)"
    s = str(value).strip()
    return s if s else "Unknown (not assigned)"


def _get_purview_bearer_token() -> str:
    # Unified Catalog APIs use the Purview data-plane scope
    token = credential.get_token("https://purview.azure.net/.default")
    return token.token


def _purview_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_purview_bearer_token()}",
        "Content-Type": "application/json",
    }


def _get_arm_bearer_token(profile: str = "default") -> str:
    # Azure Resource Graph / ARM uses ARM scope
    cred = _ARM_CREDENTIALS.get(profile)
    if cred is None:
        raise RuntimeError(f"ARM auth profile '{profile}' is not configured.")
    token = cred.get_token("https://management.azure.com/.default")
    return token.token


def _arm_headers(profile: str = "default") -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_arm_bearer_token(profile)}",
        "Content-Type": "application/json",
    }


def _normalize_sub_id(sub_id: Any) -> Optional[str]:
    if sub_id is None:
        return None
    s = str(sub_id).strip().lower()
    return s or None


def _arm_profile_for_subscription(subscription_id: Optional[str]) -> str:
    s = _normalize_sub_id(subscription_id)
    if s and s in ARM_TENANT_B_SUBSCRIPTIONS and "tenant_b" in _ARM_CREDENTIALS:
        return "tenant_b"
    return "default"


def _extract_subscription_id_from_arm_url(url: str) -> Optional[str]:
    m = re.search(r"/subscriptions/([0-9a-fA-F-]+)/", url or "", flags=re.IGNORECASE)
    return m.group(1) if m else None


def _partition_subscriptions_by_profile(subscriptions: List[str]) -> Dict[str, List[str]]:
    grouped: Dict[str, List[str]] = {}
    for sub in subscriptions or []:
        ns = _normalize_sub_id(sub)
        if not ns:
            continue
        profile = _arm_profile_for_subscription(ns)
        grouped.setdefault(profile, []).append(ns)
    return grouped


def _url(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{PURVIEW_ENDPOINT}{path}"


def _request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    url = _url(path)
    resp = requests.request(
        method=method,
        url=url,
        headers=_purview_headers(),
        params=params,
        json=body,
        timeout=HTTP_TIMEOUT,
    )

    if resp.status_code >= 400:
        try:
            err_json = resp.json()
        except Exception:
            err_json = {"raw": resp.text}

        raise RuntimeError(
            f"Purview API error {resp.status_code} calling {method} {url}: {json.dumps(err_json)[:2000]}"
        )

    if resp.text.strip() == "":
        return {}
    return resp.json()


def _paged_get(path: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Handles common { value: [...], nextLink: "..." } paging.
    """
    items: List[Dict[str, Any]] = []
    next_url: Optional[str] = None

    while True:
        if next_url:
            data = _request("GET", next_url)
        else:
            data = _request("GET", path, params=params)

        page_items = data.get("value", [])
        if isinstance(page_items, list):
            items.extend(page_items)

        next_url = data.get("nextLink")
        if not next_url:
            break

    return items


def _resource_graph_query_single_profile(
    subscriptions: List[str], query: str, profile: str
) -> List[Dict[str, Any]]:
    """
    Calls Azure Resource Graph for subscriptions that belong to a single ARM auth profile.
    Handles paging via skipToken.
    """
    if not subscriptions:
        return []

    payload: Dict[str, Any] = {
        "subscriptions": subscriptions,
        "query": query,
        "options": {"resultFormat": "objectArray"},
    }

    all_data: List[Dict[str, Any]] = []
    while True:
        resp = requests.post(
            RESOURCE_GRAPH_URL,
            headers=_arm_headers(profile),
            json=payload,
            timeout=max(60, HTTP_TIMEOUT),
        )

        if resp.status_code >= 400:
            try:
                err_json = resp.json()
            except Exception:
                err_json = {"raw": resp.text}
            raise RuntimeError(
                f"Resource Graph error {resp.status_code} (profile={profile}): {json.dumps(err_json)[:2000]}"
            )

        j = resp.json()
        all_data.extend(j.get("data", []) or [])

        skip_token = j.get("skipToken")
        if not skip_token:
            break

        payload["options"]["$skipToken"] = skip_token

    return all_data


def _resource_graph_query(subscriptions: List[str], query: str) -> List[Dict[str, Any]]:
    """
    Calls Azure Resource Graph and returns combined rows.
    Supports cross-tenant scenarios by partitioning subscriptions to the
    configured ARM credential profile (default / tenant_b).
    """
    if not subscriptions:
        raise ValueError("subscriptions is required for Resource Graph query")

    grouped = _partition_subscriptions_by_profile(subscriptions)
    all_rows: List[Dict[str, Any]] = []

    for profile, subs in grouped.items():
        logging.info("ARG query using profile=%s for %d subscription(s)", profile, len(subs))
        all_rows.extend(_resource_graph_query_single_profile(subs, query, profile))

    return all_rows



def _arm_get_json(url: str, profile: Optional[str] = None) -> Dict[str, Any]:
    """
    ARM GET helper. url must be a full https://management.azure.com/... URL

    If profile is not provided, infer the ARM auth profile from the subscription in the URL.
    Also retries once with the alternate configured profile when ARM returns
    InvalidAuthenticationTokenTenant (common in cross-tenant scenarios).
    """
    sub_id = _extract_subscription_id_from_arm_url(url)
    primary_profile = profile or _arm_profile_for_subscription(sub_id)

    candidate_profiles: List[str] = []
    if primary_profile in _ARM_CREDENTIALS:
        candidate_profiles.append(primary_profile)

    alt_profile = "tenant_b" if primary_profile == "default" else "default"
    if alt_profile in _ARM_CREDENTIALS and alt_profile not in candidate_profiles:
        candidate_profiles.append(alt_profile)

    last_error: Optional[Exception] = None

    for idx, prof in enumerate(candidate_profiles or [primary_profile]):
        resp = requests.get(
            url,
            headers=_arm_headers(prof),
            timeout=max(60, HTTP_TIMEOUT),
        )

        if resp.status_code < 400:
            if resp.text.strip() == "":
                return {}
            return resp.json()

        try:
            err_json = resp.json()
        except Exception:
            err_json = {"raw": resp.text}

        err_blob = json.dumps(err_json)[:2000]
        err_text = json.dumps(err_json)
        tenant_mismatch = (
            resp.status_code == 401
            and "InvalidAuthenticationTokenTenant" in err_text
        )

        err = RuntimeError(
            f"ARM GET error {resp.status_code} (profile={prof}) calling {url}: {err_blob}"
        )
        last_error = err

        if tenant_mismatch and idx + 1 < len(candidate_profiles):
            logging.warning(
                "ARM GET tenant mismatch for subscription %s using profile=%s. Retrying with profile=%s",
                sub_id,
                prof,
                candidate_profiles[idx + 1],
            )
            continue

        raise err

    if last_error:
        raise last_error
    raise RuntimeError(f"ARM GET failed for {url}")

def _arm_put_json(url: str, body: Dict[str, Any], profile: Optional[str] = None) -> Dict[str, Any]:
    """
    ARM PUT helper. url must be a full https://management.azure.com/... URL
    Uses same profile inference + tenant-mismatch retry behavior as _arm_get_json.
    """
    sub_id = _extract_subscription_id_from_arm_url(url)
    primary_profile = profile or _arm_profile_for_subscription(sub_id)

    candidate_profiles: List[str] = []
    if primary_profile in _ARM_CREDENTIALS:
        candidate_profiles.append(primary_profile)

    alt_profile = "tenant_b" if primary_profile == "default" else "default"
    if alt_profile in _ARM_CREDENTIALS and alt_profile not in candidate_profiles:
        candidate_profiles.append(alt_profile)

    last_error: Optional[Exception] = None

    for idx, prof in enumerate(candidate_profiles or [primary_profile]):
        resp = requests.put(
            url,
            headers=_arm_headers(prof),
            json=body,
            timeout=max(60, HTTP_TIMEOUT),
        )

        if resp.status_code < 400:
            if resp.text.strip() == "":
                return {}
            return resp.json()

        try:
            err_json = resp.json()
        except Exception:
            err_json = {"raw": resp.text}

        err_blob = json.dumps(err_json)[:2000]
        err_text = json.dumps(err_json)
        tenant_mismatch = (
            resp.status_code == 401
            and "InvalidAuthenticationTokenTenant" in err_text
        )

        err = RuntimeError(
            f"ARM PUT error {resp.status_code} (profile={prof}) calling {url}: {err_blob}"
        )
        last_error = err

        if tenant_mismatch and idx + 1 < len(candidate_profiles):
            logging.warning(
                "ARM PUT tenant mismatch for subscription %s using profile=%s. Retrying with profile=%s",
                sub_id,
                prof,
                candidate_profiles[idx + 1],
            )
            continue

        raise err

    if last_error:
        raise last_error
    raise RuntimeError(f"ARM PUT failed for {url}")


def _extract_subscription_id_from_resource_id(resource_id: str) -> str:
    if not resource_id:
        return ""
    m = re.search(r"/subscriptions/([^/]+)", resource_id, flags=re.IGNORECASE)
    return (m.group(1) if m else "").strip().lower()


def _arm_tags_default_url(resource_id: str) -> str:
    # Generic tags endpoint works for any ARM resource scope.
    # It allows reading and writing tags without needing a provider-specific api-version.
    rid = (resource_id or "").strip()
    if not rid.startswith("/"):
        rid = "/" + rid
    return f"https://management.azure.com{rid}/providers/Microsoft.Resources/tags/default?api-version=2021-04-01"


def _arm_get_tags(resource_id: str) -> Dict[str, str]:
    url = _arm_tags_default_url(resource_id)
    try:
        j = _arm_get_json(url)
    except Exception as ex:
        # If tags scope doesn't exist yet, treat as empty
        msg = str(ex)
        if "404" in msg:
            return {}
        raise
    tags = (j.get("properties") or {}).get("tags") or {}
    if isinstance(tags, dict):
        # Ensure string values
        return {str(k): str(v) for k, v in tags.items()}
    return {}


def _arm_merge_tags(resource_id: str, new_tags: Dict[str, str], dry_run: bool = True) -> Dict[str, Any]:
    """
    Merge tags at the resource scope using Microsoft.Resources/tags/default.
    Returns: {applied: bool, before: {...}, after: {...}}
    """
    before = _arm_get_tags(resource_id)
    after = dict(before)
    for k, v in (new_tags or {}).items():
        if k:
            after[str(k)] = str(v)

    if dry_run:
        return {"applied": False, "before": before, "after": after}

    body = {"properties": {"tags": after}}
    url = _arm_tags_default_url(resource_id)
    _arm_put_json(url, body)
    # Best-effort re-read for verification
    verified = _arm_get_tags(resource_id)
    return {"applied": True, "before": before, "after": verified}

def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]


def _parse_inputs(req: func.HttpRequest) -> Tuple[List[str], List[str]]:
    """
    Accepts:
      POST JSON: { "subscriptions": [...], "dataProductIds": [...] }
      or GET: ?subscriptions=sub1,sub2&dataProductId=<guid>
    """
    single_dp = req.params.get("dataProductId")
    subs_qs = req.params.get("subscriptions")

    try:
        body = req.get_json()
    except Exception:
        body = {}

    dp_ids = _coerce_list(body.get("dataProductIds"))
    subs = _coerce_list(body.get("subscriptions"))

    if not dp_ids and single_dp:
        dp_ids = [single_dp]

    if not subs and subs_qs:
        subs = [s.strip() for s in subs_qs.split(",") if s.strip()]

    if not subs:
        subs = DEFAULT_SUBSCRIPTIONS

    # normalize dp ids to lowercase (tags are lowercase by your standard)
    dp_ids = [d.strip().lower() for d in dp_ids if str(d).strip()]
    subs = [s.strip() for s in subs if str(s).strip()]

    return dp_ids, subs


def _validate_dp_ids(dp_ids: List[str]) -> Tuple[List[str], List[str]]:
    """
    Returns (valid_guids, invalid_inputs)
    """
    valid: List[str] = []
    invalid: List[str] = []
    for d in dp_ids:
        if GUID_RE.match(d):
            valid.append(d)
        else:
            invalid.append(d)
    return valid, invalid


def _score_one(found: bool, sovereignty_zone: Optional[str], resource_origin: Optional[str]) -> Dict[str, Any]:
    """
    Your rubric:
      - Resource found (dataproductid match): 20
      - sovereignty-zone tag exists: 20
      - sovereignty-zone value allowed: 20
      - resource-origin tag exists: 20
      - resource-origin value allowed: 20
    """
    score = 0

    resource_found_20 = 20 if found else 0
    score += resource_found_20

    sz = (sovereignty_zone or "").strip().lower()
    ro = (resource_origin or "").strip().lower()

    sovereignty_zone_exists_20 = 20 if (found and sz != "") else 0
    sovereignty_zone_allowed_20 = 20 if (found and sz in ALLOWED_SOVEREIGNTY_ZONE) else 0
    resource_origin_exists_20 = 20 if (found and ro != "") else 0
    resource_origin_allowed_20 = 20 if (found and ro in ALLOWED_RESOURCE_ORIGIN) else 0

    score += sovereignty_zone_exists_20
    score += sovereignty_zone_allowed_20
    score += resource_origin_exists_20
    score += resource_origin_allowed_20

    return {
        "score": score,
        "breakdown": {
            "resourceFound20": resource_found_20,
            "sovereigntyZoneExists20": sovereignty_zone_exists_20,
            "sovereigntyZoneAllowed20": sovereignty_zone_allowed_20,
            "resourceOriginExists20": resource_origin_exists_20,
            "resourceOriginAllowed20": resource_origin_allowed_20,
        },
        "normalized": {
            "sovereignty-zone": sz or None,
            "resource-origin": ro or None,
        }
    }


def _kql_escape(s: str) -> str:
    # Kusto single-quote escaping is doubling single quotes.
    return s.replace("'", "''")


def _kql_in_list(values: List[str]) -> str:
    # Produces: 'a','b','c' (values already normalized as needed)
    return ", ".join([f"'{_kql_escape(v)}'" for v in values])


def _chunk_list(items: List[str], chunk_size: int) -> List[List[str]]:
    if chunk_size <= 0:
        return [items]
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def _is_non_applicable_type(resource_type: str) -> bool:
    rt = (resource_type or "").strip().lower()
    for prefix in NON_APPLICABLE_TYPE_PREFIXES:
        if rt.startswith(prefix):
            return True
    return False


def _defender_candidate_plans_for_resource_type(resource_type: str) -> List[str]:
    """
    Returns lowercase Defender plan names that are acceptable for this resource type.
    We keep it flexible: "any flavor of defender would do".
    """
    rt = (resource_type or "").strip().lower()

    # Not applicable / cannot configure
    if _is_non_applicable_type(rt):
        return []

    # Compute
    if rt == "microsoft.compute/virtualmachines":
        # Accept either Defender for Servers (VirtualMachines) OR SQL VM plan, if that's what they enabled
        return ["virtualmachines", "sqlservervirtualmachines"]

    # Arc-enabled / hybrid machines
    if rt == "microsoft.hybridcompute/machines":
        # Defender for Servers coverage for Arc-enabled servers is represented through the Servers plan.
        return ["virtualmachines"]

    # SQL (PaaS/IaaS SQL resources)
    if rt.startswith("microsoft.sql/"):
        # Accept either SQL plan (SqlServers) OR SQL VM plan
        return ["sqlservers", "sqlservervirtualmachines"]

    # Storage (ADLS / Azure Files via Storage Account)
    if rt == "microsoft.storage/storageaccounts":
        return ["storageaccounts"]

    # Unknown / out of scope => treat as "cannot be configured" => N/A
    return []


def _parse_na_dp_ids(req: func.HttpRequest) -> List[str]:
    """
    Optional override: caller can pass dpIds that should be treated as Not Applicable (N/A => 100),
    for example Fabric data products.
    Supports:
      POST JSON: { "naDataProductIds": [...] }
      GET: ?naDataProductIds=guid1,guid2
    """
    na_ids: List[str] = []

    na_qs = req.params.get("naDataProductIds")
    if na_qs:
        na_ids.extend([x.strip() for x in na_qs.split(",") if x.strip()])

    try:
        body = req.get_json()
    except Exception:
        body = {}

    na_ids.extend(_coerce_list(body.get("naDataProductIds")))

    # normalize + validate
    na_ids_norm = [x.strip().lower() for x in na_ids if str(x).strip()]
    na_valid, _ = _validate_dp_ids(na_ids_norm)
    return na_valid




def _coerce_json_value(value: Any) -> Any:
    """Best-effort conversion for ARG dynamic values that may arrive as dict/list/JSON string."""
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return s
    return value


def _sum_patch_counts(value: Any) -> Optional[int]:
    """
    Sums availablePatchCountByClassification regardless of whether ARG returned it as
    a dynamic object, JSON string, list, or scalar.
    """
    v = _coerce_json_value(value)
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        return None
    if isinstance(v, dict):
        total = 0
        seen = False
        for child in v.values():
            child_total = _sum_patch_counts(child)
            if child_total is not None:
                total += child_total
                seen = True
        return total if seen else 0
    if isinstance(v, list):
        total = 0
        seen = False
        for child in v:
            child_total = _sum_patch_counts(child)
            if child_total is not None:
                total += child_total
                seen = True
        return total if seen else 0
    return None


def _assessment_resource_id_for_target_resource(resource_id: Optional[str]) -> Optional[str]:
    rid = (resource_id or "").strip()
    if not rid:
        return None
    return rid.rstrip("/") + "/patchAssessmentResults/latest"

# -----------------------------
# Purview lookups
# -----------------------------
def find_data_product_by_name(name: str) -> Dict[str, Any]:
    body = {"nameKeyword": name, "skip": 0, "top": 10}
    data = _request(
        "POST",
        "/datagovernance/catalog/dataProducts/query",
        params={"api-version": PURVIEW_API_VERSION},
        body=body,
    )

    candidates = data.get("value", []) or []
    if not candidates:
        raise ValueError(f"No data product found for nameKeyword='{name}'")

    name_lower = name.strip().lower()
    for dp in candidates:
        if (dp.get("name") or "").strip().lower() == name_lower:
            return dp

    return candidates[0]


def find_term_by_name(term_name: str) -> Dict[str, Any]:
    terms = _paged_get(
        "/datagovernance/catalog/terms",
        params={
            "api-version": PURVIEW_API_VERSION,
            "keyword": term_name,
            "skip": 0,
            "top": 50,
        },
    )

    if not terms:
        raise ValueError(f"No glossary term found for keyword='{term_name}'")

    t_lower = term_name.strip().lower()
    for t in terms:
        if (t.get("name") or "").strip().lower() == t_lower:
            return t

    return terms[0]


def list_data_product_term_relationships(data_product_id: str) -> List[Dict[str, Any]]:
    return _paged_get(
        f"/datagovernance/catalog/dataProducts/{data_product_id}/relationships",
        params={
            "api-version": PURVIEW_API_VERSION,
            "entityType": "TERM",
        },
    )


def get_term(term_id: str) -> Dict[str, Any]:
    return _request(
        "GET",
        f"/datagovernance/catalog/terms/{term_id}",
        params={"api-version": PURVIEW_API_VERSION},
    )


def resolve_residency_term_for_data_product(
    data_product_name: str,
    parent_term_name: str = DEFAULT_PARENT_TERM_NAME
) -> Dict[str, Any]:
    dp = find_data_product_by_name(data_product_name)
    dp_id = dp.get("id")
    if not dp_id:
        raise RuntimeError("Purview response missing dataProduct.id")

    parent_term = find_term_by_name(parent_term_name)
    parent_term_id = parent_term.get("id")
    if not parent_term_id:
        raise RuntimeError("Purview response missing term.id for parent term")

    relationships = list_data_product_term_relationships(dp_id)

    term_ids: List[str] = []
    for r in relationships:
        term_id = r.get("entityId")
        if term_id:
            term_ids.append(term_id)

    residency_terms: List[Dict[str, Any]] = []
    for tid in term_ids:
        t = get_term(tid)
        if t.get("parentId") == parent_term_id:
            residency_terms.append({
                "termId": t.get("id"),
                "termName": t.get("name"),
                "parentId": t.get("parentId"),
            })

    raw_residency = residency_terms[0].get("termName") if residency_terms else None
    residency_value = normalize_residency(raw_residency)

    return {
        "dataProductName": dp.get("name") or data_product_name,
        "dataProductId": dp_id,
        "parentTermName": parent_term.get("name") or parent_term_name,
        "parentTermId": parent_term_id,
        "residencyTerms": residency_terms,
        "residency": residency_value,
    }


def build_missing_residency_response(data_product_name: str, parent_term_name: str) -> Dict[str, Any]:
    return {
        "dataProductName": data_product_name,
        "dataProductId": None,
        "parentTermName": parent_term_name,
        "parentTermId": None,
        "residencyTerms": [],
        "residency": "Unknown (not assigned)",
    }


# -----------------------------


def _try_get_json(req: func.HttpRequest) -> Dict[str, Any]:
    try:
        body = req.get_json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "t", "yes", "y"}:
        return True
    if s in {"0", "false", "f", "no", "n"}:
        return False
    return default


def _norm_code(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().lower()
    return s if s else None


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _json_http(payload: Dict[str, Any], status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, default=_json_default),
        status_code=status_code,
        mimetype="application/json",
    )


def find_data_product_by_id(data_product_id: str) -> Optional[Dict[str, Any]]:
    """
    Best-effort lookup. If this fails (permissions/API differences), we don't block update flow.
    """
    try:
        return _request(
            "GET",
            f"/datagovernance/catalog/dataProducts/{data_product_id}",
            params={"api-version": PURVIEW_API_VERSION},
        )
    except Exception as ex:
        logging.warning("find_data_product_by_id failed for %s: %s", data_product_id, str(ex)[:500])
        return None


def _safe_term_summary(term: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not term:
        return None
    return {
        "termId": term.get("id"),
        "termName": term.get("name"),
        "parentId": term.get("parentId"),
    }


def resolve_residency_term_for_data_product_id(
    data_product_id: str,
    parent_term_name: str = DEFAULT_PARENT_TERM_NAME
) -> Dict[str, Any]:
    if not GUID_RE.match((data_product_id or "").strip()):
        raise ValueError(f"Invalid dataProductId GUID: '{data_product_id}'")

    dp = find_data_product_by_id(data_product_id) or {}
    parent_term = find_term_by_name(parent_term_name)
    parent_term_id = parent_term.get("id")
    if not parent_term_id:
        raise RuntimeError("Purview response missing term.id for parent term")

    relationships = list_data_product_term_relationships(data_product_id)

    term_ids: List[str] = []
    for r in relationships:
        tid = r.get("entityId")
        if tid:
            term_ids.append(tid)

    residency_terms: List[Dict[str, Any]] = []
    for tid in term_ids:
        try:
            t = get_term(tid)
        except Exception as ex:
            logging.warning("get_term failed for termId=%s: %s", tid, str(ex)[:500])
            continue

        if t.get("parentId") == parent_term_id:
            residency_terms.append({
                "termId": t.get("id"),
                "termName": t.get("name"),
                "parentId": t.get("parentId"),
            })

    raw_residency = residency_terms[0].get("termName") if residency_terms else None
    residency_value = normalize_residency(raw_residency)

    return {
        "dataProductName": (dp.get("name") or dp.get("displayName") or None),
        "dataProductId": data_product_id,
        "parentTermName": parent_term.get("name") or parent_term_name,
        "parentTermId": parent_term_id,
        "residencyTerms": residency_terms,
        "residency": residency_value,
    }


def find_child_term_under_parent_by_name(child_term_name: str, parent_term_id: str) -> Dict[str, Any]:
    """
    Finds exact child term by name (case-insensitive) and parentId.
    Expected child names are your lowercase region codes (e.g., eastus2).
    """
    terms = _paged_get(
        "/datagovernance/catalog/terms",
        params={
            "api-version": PURVIEW_API_VERSION,
            "keyword": child_term_name,
            "skip": 0,
            "top": 100,
        },
    )

    if not terms:
        raise ValueError(f"No glossary term found for keyword='{child_term_name}'")

    target = (child_term_name or "").strip().lower()
    exact_under_parent: List[Dict[str, Any]] = []

    for t in terms:
        t_name = (t.get("name") or "").strip().lower()
        t_parent = t.get("parentId")
        if t_name == target and t_parent == parent_term_id:
            exact_under_parent.append(t)

    if not exact_under_parent:
        raise ValueError(
            f"Child term '{child_term_name}' not found under parent term id '{parent_term_id}'."
        )

    # If multiple exact matches somehow exist, pick first but log it.
    if len(exact_under_parent) > 1:
        logging.warning(
            "Multiple exact child terms found under parent for '%s'; using first. count=%d",
            child_term_name,
            len(exact_under_parent),
        )

    return exact_under_parent[0]


def delete_data_product_term_relationship(data_product_id: str, term_id: str) -> None:
    """
    Delete Data Product <-> TERM relationship by entityId (term_id).
    Docs endpoint shape:
      DELETE /dataProducts/{id}/relationships?entityType=TERM&entityId=<term_id>
    """
    _request(
        "DELETE",
        f"/datagovernance/catalog/dataProducts/{data_product_id}/relationships",
        params={
            "api-version": PURVIEW_API_VERSION,
            "entityType": "TERM",
            "entityId": term_id,
        },
    )


def create_data_product_term_relationship(data_product_id: str, term_id: str) -> Dict[str, Any]:
    """
    Create Data Product <-> TERM relationship.
    We try the simple payload first, then a wrapped payload fallback.
    """
    params = {
        "api-version": PURVIEW_API_VERSION,
        "entityType": "TERM",
    }

    body_simple = {
        "relationshipType": "Related",
        "entityId": term_id,
    }

    try:
        return _request(
            "POST",
            f"/datagovernance/catalog/dataProducts/{data_product_id}/relationships",
            params=params,
            body=body_simple,
        )
    except Exception as ex1:
        logging.warning("Simple relationship create payload failed; trying wrapped payload. %s", str(ex1)[:500])

    body_wrapped = {
        "relationship1": {
            "relationshipType": "Related",
            "entityId": term_id,
        }
    }

    return _request(
        "POST",
        f"/datagovernance/catalog/dataProducts/{data_product_id}/relationships",
        params=params,
        body=body_wrapped,
    )


def _build_copilot_action_log_record(
    data_product_id: str,
    data_product_name: Optional[str],
    parent_term_name: str,
    current_code: Optional[str],
    target_code: Optional[str],
    action: str,
    status: str,
    dry_run: bool,
    source: Optional[str],
    actor: Optional[str],
    request_id: Optional[str],
    notes: Optional[List[str]] = None,
    raw_action_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build an action log record aligned to Fabric table: dp_copilot_purview_changelog.

    Notes:
      - This record can be returned to callers AND also persisted directly from the function app
        if FABRIC_SQL_LOGGING_ENABLED=true.
      - Column names match the table schema (see your dp_copilot_purview_changelog query).
    """
    now_utc = datetime.now(timezone.utc)
    record = {
        "ActionTimeUtc": now_utc,
        "ActionType": "PurviewResidencyGlossaryUpdate",
        "ActionStatus": status,  # preview|applied|no_change|blocked|error
        "DryRun": bool(dry_run),
        "DataProductID": data_product_id,
        "DataProductDisplayName": data_product_name,
        "ParentTermName": parent_term_name,
        "CurrentResidencyCode": current_code,
        "TargetResidencyCode": target_code,
        "RequestedBy": actor,
        "RequestSource": source,
        "RequestId": request_id,
        "ActionDecision": action,  # add|replace|none|manual_review
        "Notes": "; ".join(notes or []),
        "IngestedAtUtc": now_utc,
        "RawActionLogRecordJson": json.dumps(raw_action_payload or {}, default=str) if raw_action_payload is not None else None,
    }
    return record


def _build_cc_changelog_record(
    *,
    data_product_id: Optional[str],
    data_product_name: Optional[str],
    cc_score_pct: Optional[int],
    owner_email: Optional[str],
    resource_id: Optional[str],
    tag_key: Optional[str],
    tag_value: Optional[str],
    status: str,
    dry_run: bool,
    source: Optional[str],
    actor: Optional[str],
    request_id: Optional[str],
    notes: Optional[List[str]] = None,
    raw_action_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an action log record aligned to Fabric table: dp_copilot_cc_changelog."""
    now_utc = datetime.now(timezone.utc)
    return {
        "ActionTimeUtc": now_utc,
        "ActionType": "CCPIIInvestigateTag",
        "ActionStatus": status,  # preview|applied|no_change|blocked|error
        "DryRun": bool(dry_run),
        "DataProductID": data_product_id,
        "DataProductDisplayName": data_product_name,
        "CCScorePct": cc_score_pct,
        "OwnerEmail": owner_email,
        "ResourceId": resource_id,
        "SuggestedTagKey": tag_key,
        "SuggestedTagValue": tag_value,
        "RequestedBy": actor,
        "RequestSource": source,
        "RequestId": request_id,
        "Notes": "; ".join(notes or []),
        "IngestedAtUtc": now_utc,
        "RawActionLogRecordJson": json.dumps(raw_action_payload or {}, default=str) if raw_action_payload is not None else None,
    }


def _parse_residency_update_request(req: func.HttpRequest) -> Dict[str, Any]:
    body = _try_get_json(req)

    # Querystring takes precedence only if supplied; otherwise body
    data_product_id = (req.params.get("dataProductId") or body.get("dataProductId") or "").strip().lower()
    target_residency_code = _norm_code(req.params.get("targetResidencyCode") or body.get("targetResidencyCode"))
    parent_term_name = (req.params.get("parentTermName") or body.get("parentTermName") or DEFAULT_PARENT_TERM_NAME).strip()

    # Track whether caller explicitly sent expectedCurrentResidencyCode (for optimistic check)
    expected_in_qs = "expectedCurrentResidencyCode" in req.params
    expected_in_body = isinstance(body, dict) and ("expectedCurrentResidencyCode" in body)
    expected_provided = expected_in_qs or expected_in_body
    expected_current_residency_code = _norm_code(
        req.params.get("expectedCurrentResidencyCode")
        if expected_in_qs
        else body.get("expectedCurrentResidencyCode")
    )

    dry_run = _to_bool(req.params.get("dryRun") if "dryRun" in req.params else body.get("dryRun"), default=True)
    confirm = _to_bool(req.params.get("confirm") if "confirm" in req.params else body.get("confirm"), default=False)

    source = (req.params.get("source") or body.get("source") or "CopilotStudio").strip()
    actor = (req.params.get("actor") or body.get("actor") or "").strip() or None
    request_id = (req.params.get("requestId") or body.get("requestId") or "").strip() or None

    return {
        "dataProductId": data_product_id,
        "targetResidencyCode": target_residency_code,
        "parentTermName": parent_term_name or DEFAULT_PARENT_TERM_NAME,
        "expectedCurrentResidencyCode": expected_current_residency_code,
        "expectedCurrentResidencyCodeProvided": expected_provided,
        "dryRun": dry_run,
        "confirm": confirm,
        "source": source,
        "actor": actor,
        "requestId": request_id,
        "rawBody": body,
    }


def _build_residency_update_preview(plan_req: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    data_product_id = plan_req["dataProductId"]
    target_code = plan_req["targetResidencyCode"]
    parent_term_name = plan_req["parentTermName"]
    expected_current_code = plan_req["expectedCurrentResidencyCode"]
    expected_current_provided = plan_req["expectedCurrentResidencyCodeProvided"]
    dry_run = plan_req["dryRun"]
    source = plan_req["source"]
    actor = plan_req["actor"]
    request_id = plan_req["requestId"]

    # Basic validation
    if not data_product_id:
        return 400, {
            "error": "Missing required parameter 'dataProductId'.",
            "example": {
                "dataProductId": "00000000-0000-0000-0000-000000000001",
                "targetResidencyCode": "eastus2",
                "expectedCurrentResidencyCode": None,
                "dryRun": True
            }
        }

    if not GUID_RE.match(data_product_id):
        return 400, {
            "error": "Invalid 'dataProductId'. Expected GUID.",
            "dataProductId": data_product_id,
        }

    if not target_code:
        return 400, {
            "error": "Missing required parameter 'targetResidencyCode'.",
            "hint": "Pass the approved lowercase region_code from rs_approved_regions (e.g., eastus, eastus2)."
        }

    if "," in target_code:
        return 400, {
            "error": "targetResidencyCode must be a single region code (deterministic single value).",
            "targetResidencyCode": target_code,
        }

    notes: List[str] = []

    # Parent + target child term resolution
    parent_term = find_term_by_name(parent_term_name)
    parent_term_id = parent_term.get("id")
    if not parent_term_id:
        return 500, {"error": "Parent term found but missing id.", "parentTermName": parent_term_name}

    target_term = find_child_term_under_parent_by_name(target_code, parent_term_id)

    # Current state by DP id
    current_state = resolve_residency_term_for_data_product_id(data_product_id, parent_term_name=parent_term_name)
    dp_name = current_state.get("dataProductName")

    residency_terms = current_state.get("residencyTerms") or []
    if len(residency_terms) > 1:
        notes.append("Multiple child terms are assigned under the residency parent term; manual review required.")
        payload = {
            "ok": True,
            "canApply": False,
            "needsChange": None,
            "manualReviewRequired": True,
            "dryRun": dry_run,
            "dataProductId": data_product_id,
            "dataProductDisplayName": dp_name,
            "parentTermName": current_state.get("parentTermName") or parent_term_name,
            "parentTermId": current_state.get("parentTermId") or parent_term_id,
            "currentResidencyTerms": residency_terms,
            "targetResidencyTerm": _safe_term_summary(target_term),
            "targetResidencyCode": target_code,
            "expectedCurrentResidencyCode": expected_current_code,
            "action": "manual_review",
            "operations": [],
            "notes": notes,
        }
        payload["actionLogRecord"] = _build_copilot_action_log_record(
            data_product_id=data_product_id,
            data_product_name=dp_name,
            parent_term_name=payload["parentTermName"],
            current_code=None,
            target_code=target_code,
            action="manual_review",
            status="blocked",
            dry_run=dry_run,
            source=source,
            actor=actor,
            request_id=request_id,
            notes=notes,
        )
        return 200, payload

    current_term = residency_terms[0] if residency_terms else None
    current_code = _norm_code((current_term or {}).get("termName"))

    # Optimistic concurrency / stale preview protection
    if expected_current_provided:
        # expected=None means caller expects "missing"
        if expected_current_code != current_code:
            notes.append("Purview current residency changed since preview or caller expectation is stale.")
            payload = {
                "ok": True,
                "canApply": False,
                "needsChange": None,
                "conflict": True,
                "dryRun": dry_run,
                "dataProductId": data_product_id,
                "dataProductDisplayName": dp_name,
                "parentTermName": current_state.get("parentTermName") or parent_term_name,
                "parentTermId": current_state.get("parentTermId") or parent_term_id,
                "currentResidencyTerm": current_term,
                "currentResidencyCode": current_code,
                "targetResidencyTerm": _safe_term_summary(target_term),
                "targetResidencyCode": target_code,
                "expectedCurrentResidencyCode": expected_current_code,
                "action": "none",
                "operations": [],
                "notes": notes,
            }
            payload["actionLogRecord"] = _build_copilot_action_log_record(
                data_product_id=data_product_id,
                data_product_name=dp_name,
                parent_term_name=payload["parentTermName"],
                current_code=current_code,
                target_code=target_code,
                action="none",
                status="blocked",
                dry_run=dry_run,
                source=source,
                actor=actor,
                request_id=request_id,
                notes=notes,
            )
            return 409, payload

    operations: List[Dict[str, Any]] = []
    action = "none"
    needs_change = False
    can_apply = True

    target_term_id = target_term.get("id")
    target_term_name = target_term.get("name")

    if current_code == target_code:
        action = "none"
        needs_change = False
        notes.append("Purview residency already matches target Azure residency code.")
    elif current_term is None:
        action = "add"
        needs_change = True
        operations.append({
            "step": 1,
            "operation": "addTermRelationship",
            "entityType": "TERM",
            "termId": target_term_id,
            "termName": target_term_name,
        })
    else:
        # Replace wrong value: remove old child under Gl-Region, add new one
        action = "replace"
        needs_change = True
        operations.append({
            "step": 1,
            "operation": "deleteTermRelationship",
            "entityType": "TERM",
            "termId": current_term.get("termId"),
            "termName": current_term.get("termName"),
        })
        operations.append({
            "step": 2,
            "operation": "addTermRelationship",
            "entityType": "TERM",
            "termId": target_term_id,
            "termName": target_term_name,
        })

    payload = {
        "ok": True,
        "canApply": can_apply,
        "needsChange": needs_change,
        "manualReviewRequired": False,
        "conflict": False,
        "dryRun": dry_run,
        "dataProductId": data_product_id,
        "dataProductDisplayName": dp_name,
        "parentTermName": current_state.get("parentTermName") or parent_term_name,
        "parentTermId": current_state.get("parentTermId") or parent_term_id,
        "currentResidencyTerm": current_term,
        "currentResidencyCode": current_code,
        "targetResidencyTerm": _safe_term_summary(target_term),
        "targetResidencyCode": target_code,
        "expectedCurrentResidencyCode": expected_current_code,
        "action": action,
        "operations": operations,
        "notes": notes,
        # Return a ready-to-persist log payload (Fabric can write this to dp_copilot_actions)
        "actionLogRecord": _build_copilot_action_log_record(
            data_product_id=data_product_id,
            data_product_name=dp_name,
            parent_term_name=current_state.get("parentTermName") or parent_term_name,
            current_code=current_code,
            target_code=target_code,
            action=action,
            status="preview" if needs_change else "no_change",
            dry_run=dry_run,
            source=source,
            actor=actor,
            request_id=request_id,
            notes=notes,
        ),
    }

    return 200, payload


def _normalize_sql_table_name(table_name: str) -> str:
    # Accept "schema.table" or "table" and return a safely bracketed "[schema].[table]" string.
    t = (table_name or "").strip()
    if not t:
        return ""
    if "." in t:
        schema, table = [p.strip().strip("[]") for p in t.split(".", 1)]
    else:
        schema, table = "dbo", t.strip().strip("[]")
    return f"[{schema}].[{table}]"


def _fabric_sql_insert_row(table_name: str, columns: List[str], row: Dict[str, Any]) -> bool:
    """Best-effort INSERT into Fabric SQL endpoint. Returns True if inserted, else False."""
    if not FABRIC_SQL_LOGGING_ENABLED:
        return False
    if not FABRIC_SQL_SERVER or not FABRIC_SQL_DATABASE:
        logging.warning("FABRIC_SQL_LOGGING_ENABLED is true but FABRIC_SQL_SERVER/DATABASE are not set. Skipping SQL insert.")
        return False

    try:
        import struct  # noqa: F401
        import pyodbc  # type: ignore
    except Exception as ex:
        logging.warning("pyodbc not available in Function runtime; skipping Fabric SQL insert. %s", str(ex)[:300])
        return False

    # Acquire AAD token for SQL
    try:
        sql_token = DefaultAzureCredential().get_token("https://database.windows.net/.default").token
    except Exception as ex:
        logging.warning("Failed to acquire SQL access token via DefaultAzureCredential; skipping Fabric SQL insert. %s", str(ex)[:300])
        return False

    # pyodbc expects token bytes in UTF-16-LE
    token_bytes = bytes(sql_token, "utf-16-le")
    SQL_COPT_SS_ACCESS_TOKEN = 1256

    conn_str = (
        f"Driver={{{FABRIC_SQL_DRIVER}}};"
        f"Server=tcp:{FABRIC_SQL_SERVER},1433;"
        f"Database={FABRIC_SQL_DATABASE};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )

    table_sql = _normalize_sql_table_name(table_name)
    if not table_sql:
        return False

    cols_sql = ", ".join([f"[{c}]" for c in columns])
    params_sql = ", ".join(["?"] * len(columns))
    insert_sql = f"INSERT INTO {table_sql} ({cols_sql}) VALUES ({params_sql})"

    # Build values; allow datetime objects
    values = []
    for c in columns:
        v = row.get(c)
        # Normalize booleans and None
        if isinstance(v, bool):
            values.append(1 if v else 0)
        else:
            values.append(v)

    try:
        conn = pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_bytes})
        try:
            cur = conn.cursor()
            cur.execute(insert_sql, values)
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return True
    except Exception as ex:
        logging.warning("Fabric SQL insert failed (%s). %s", table_name, str(ex)[:500])
        return False


def _emit_action_log_stub(log_record: Dict[str, Any]) -> None:
    """
    Persist Copilot action logs.

    - Always logs to App Insights / function logs.
    - If FABRIC_SQL_LOGGING_ENABLED=true, also inserts into Fabric SQL changelog tables:
        * Purview: dp_copilot_purview_changelog
        * CC/PII: dp_copilot_cc_changelog
    """
    try:
        # Ensure timestamps exist
        now_utc = datetime.now(timezone.utc)
        if not log_record.get("ActionTimeUtc"):
            log_record["ActionTimeUtc"] = now_utc
        if not log_record.get("IngestedAtUtc"):
            log_record["IngestedAtUtc"] = now_utc

        # If caller didn't provide a raw JSON blob, store the whole record as a JSON string
        if not log_record.get("RawActionLogRecordJson"):
            log_record["RawActionLogRecordJson"] = json.dumps(log_record, default=str)

        logging.info("COPILOT_ACTION_LOG %s", json.dumps(log_record, default=str))

        action_type = (log_record.get("ActionType") or "").strip()
        if action_type.lower().startswith("purview"):
            table = FABRIC_CHANGELOG_TABLE_PURVIEW
            cols = [
                "ActionTimeUtc", "ActionType", "ActionStatus", "DryRun",
                "DataProductID", "DataProductDisplayName",
                "ParentTermName", "CurrentResidencyCode", "TargetResidencyCode",
                "RequestedBy", "RequestSource", "RequestId",
                "ActionDecision", "Notes",
                "IngestedAtUtc", "RawActionLogRecordJson",
            ]
        else:
            # Default: CC/PII changelog
            table = FABRIC_CHANGELOG_TABLE_CC
            cols = [
                "ActionTimeUtc", "ActionType", "ActionStatus", "DryRun",
                "DataProductID", "DataProductDisplayName",
                "CCScorePct", "OwnerEmail", "ResourceId",
                "SuggestedTagKey", "SuggestedTagValue",
                "RequestedBy", "RequestSource", "RequestId",
                "Notes", "IngestedAtUtc", "RawActionLogRecordJson",
            ]

        _fabric_sql_insert_row(table, cols, log_record)

    except Exception:
        # Never break the business action because logging failed
        logging.info("COPILOT_ACTION_LOG (failed to emit)")


def _apply_residency_update(plan_req: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    status_code, preview = _build_residency_update_preview(plan_req)

    # If preview failed / conflict / blocked, return as-is
    if status_code != 200:
        return status_code, preview

    dry_run = bool(plan_req["dryRun"])
    confirm = bool(plan_req["confirm"])
    source = plan_req["source"]
    actor = plan_req["actor"]
    request_id = plan_req["requestId"]

    # If no change needed, return success (idempotent)
    if not preview.get("needsChange"):
        log_record = preview.get("actionLogRecord") or {}
        log_record["ActionStatus"] = "no_change"
        _emit_action_log_stub(log_record)

        preview["applied"] = False
        preview["message"] = "No change needed."
        preview["actionLogRecord"] = log_record
        return 200, preview

    # dryRun apply endpoint still returns preview only
    if dry_run:
        log_record = preview.get("actionLogRecord") or {}
        log_record["ActionStatus"] = "preview"
        _emit_action_log_stub(log_record)

        preview["applied"] = False
        preview["message"] = "Dry run only. No changes were written to Purview."
        preview["actionLogRecord"] = log_record
        return 200, preview

    # Hard confirmation required for real write
    if not confirm:
        return 400, {
            "error": "Missing confirmation. For a real write, send confirm=true and dryRun=false.",
            "hint": "Use preview first, then apply with confirm=true.",
            "preview": preview,
        }

    data_product_id = preview["dataProductId"]
    action = preview.get("action")
    current_term = preview.get("currentResidencyTerm")
    target_term = preview.get("targetResidencyTerm")
    steps_executed: List[Dict[str, Any]] = []

    try:
        if action == "add":
            create_data_product_term_relationship(data_product_id, target_term["termId"])
            steps_executed.append({
                "operation": "addTermRelationship",
                "termId": target_term["termId"],
                "termName": target_term["termName"],
                "status": "success",
            })

        elif action == "replace":
            # Replace = delete wrong child under Gl-Region, then add target child
            if current_term and current_term.get("termId"):
                delete_data_product_term_relationship(data_product_id, current_term["termId"])
                steps_executed.append({
                    "operation": "deleteTermRelationship",
                    "termId": current_term["termId"],
                    "termName": current_term.get("termName"),
                    "status": "success",
                })

            create_data_product_term_relationship(data_product_id, target_term["termId"])
            steps_executed.append({
                "operation": "addTermRelationship",
                "termId": target_term["termId"],
                "termName": target_term["termName"],
                "status": "success",
            })

        else:
            # none/manual_review should have already been handled earlier
            pass

        # Re-read final state for verification
        post_state = resolve_residency_term_for_data_product_id(
            data_product_id,
            parent_term_name=preview.get("parentTermName") or DEFAULT_PARENT_TERM_NAME,
        )

        post_terms = post_state.get("residencyTerms") or []
        post_current = post_terms[0] if post_terms else None
        post_current_code = _norm_code((post_current or {}).get("termName"))
        target_code = _norm_code(preview.get("targetResidencyCode"))

        verified_match = (post_current_code == target_code)

        notes = list(preview.get("notes") or [])
        if verified_match:
            notes.append("Post-update verification succeeded.")
        else:
            notes.append("Post-update verification did not match target value. Manual review may be required.")

        log_record = _build_copilot_action_log_record(
            data_product_id=preview["dataProductId"],
            data_product_name=preview.get("dataProductDisplayName"),
            parent_term_name=preview.get("parentTermName") or DEFAULT_PARENT_TERM_NAME,
            current_code=_norm_code((preview.get("currentResidencyTerm") or {}).get("termName")),
            target_code=target_code,
            action=action or "none",
            status="applied" if verified_match else "error",
            dry_run=False,
            source=source,
            actor=actor,
            request_id=request_id,
            notes=notes,
        )
        _emit_action_log_stub(log_record)

        return 200, {
            **preview,
            "applied": True,
            "dryRun": False,
            "confirm": True,
            "stepsExecuted": steps_executed,
            "postState": {
                "dataProductId": post_state.get("dataProductId"),
                "dataProductName": post_state.get("dataProductName"),
                "parentTermName": post_state.get("parentTermName"),
                "residencyTerms": post_state.get("residencyTerms"),
                "residency": post_state.get("residency"),
                "currentResidencyCode": post_current_code,
            },
            "verifiedMatch": verified_match,
            "actionLogRecord": log_record,
            "message": "Purview residency glossary updated." if verified_match else "Update executed but verification mismatch detected.",
        }

    except Exception as ex:
        log_record = preview.get("actionLogRecord") or {}
        log_record["ActionStatus"] = "error"
        log_record["Notes"] = ((log_record.get("Notes") or "") + "; " if log_record.get("Notes") else "") + f"Apply failed: {str(ex)[:500]}"
        _emit_action_log_stub(log_record)

        return 500, {
            "error": "Failed to apply Purview residency glossary update.",
            "details": str(ex)[:2000],
            "preview": preview,
            "stepsExecuted": steps_executed,
            "actionLogRecord": log_record,
        }

# Azure Function routes
# -----------------------------
@app.route(route="purview/residency", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def purview_residency(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data_product_name = req.params.get("dataProductName")
        parent_term_name = req.params.get("parentTermName")

        if not data_product_name:
            try:
                body = req.get_json()
            except Exception:
                body = {}
            data_product_name = body.get("dataProductName")
            parent_term_name = parent_term_name or body.get("parentTermName")

        if not data_product_name:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required parameter 'dataProductName'. Provide as querystring or JSON body.",
                    "example": {
                        "dataProductName": "Fabric Lakehouse - ERP - ExampleCorp",
                        "parentTermName": "Gl-Region"
                    }
                }),
                status_code=400,
                mimetype="application/json",
            )

        parent_term_name_final = parent_term_name or DEFAULT_PARENT_TERM_NAME

        try:
            result = resolve_residency_term_for_data_product(
                data_product_name=data_product_name,
                parent_term_name=parent_term_name_final,
            )
        except ValueError:
            result = build_missing_residency_response(data_product_name, parent_term_name_final)

        result["residency"] = normalize_residency(result.get("residency"))

        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logging.exception("Unhandled error in purview_residency")
        return func.HttpResponse(
            json.dumps({
                "error": "Unhandled exception",
                "details": str(e)[:2000]
            }),
            status_code=500,
            mimetype="application/json",
        )




@app.route(route="purview/residencyUpdatePreview", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def purview_residency_update_preview(req: func.HttpRequest) -> func.HttpResponse:
    """
    Preview-only endpoint for Copilot 2-step confirmation flow.
    Caller should pass:
      - dataProductId (GUID) [preferred]
      - targetResidencyCode (lowercase, approved region code from rs_approved_regions.region_code)
      - expectedCurrentResidencyCode (optional; null/blank means "expect missing")
      - dryRun (optional, default true)
      - parentTermName (optional, defaults to Gl-Region)
      - source / actor / requestId (optional metadata)
    """
    try:
        plan_req = _parse_residency_update_request(req)
        status_code, payload = _build_residency_update_preview(plan_req)
        return _json_http(payload, status_code=status_code)
    except Exception as e:
        logging.exception("Unhandled error in purview_residency_update_preview")
        return _json_http(
            {
                "error": "Unhandled exception",
                "details": str(e)[:2000],
            },
            status_code=500,
        )


@app.route(route="purview/residencyUpdateApply", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def purview_residency_update_apply(req: func.HttpRequest) -> func.HttpResponse:
    """
    Apply endpoint for Copilot 2-step confirmation flow.
    Safe defaults:
      - dryRun defaults to true
      - real write requires: dryRun=false AND confirm=true

    Typical real-write payload:
    {
      "dataProductId": "00000000-0000-0000-0000-000000000001",
      "targetResidencyCode": "eastus2",
      "expectedCurrentResidencyCode": null,
      "dryRun": false,
      "confirm": true,
      "source": "CopilotStudio",
      "actor": "user@example.com",
      "requestId": "optional-guid"
    }
    """
    try:
        plan_req = _parse_residency_update_request(req)
        status_code, payload = _apply_residency_update(plan_req)
        return _json_http(payload, status_code=status_code)
    except Exception as e:
        logging.exception("Unhandled error in purview_residency_update_apply")
        return _json_http(
            {
                "error": "Unhandled exception",
                "details": str(e)[:2000],
            },
            status_code=500,
        )

# Azure tag compliance lookup (Resource Graph)
# IMPORTANT: auth_level MUST be ANONYMOUS so the Functions runtime does NOT require a function key.
# EasyAuth (Entra) is the gate.
@app.route(route="azure/tagCompliance", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def azure_tag_compliance(req: func.HttpRequest) -> func.HttpResponse:
    try:
        dp_ids_raw, subs = _parse_inputs(req)

        if not dp_ids_raw:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required 'dataProductIds' (POST JSON) or 'dataProductId' (querystring).",
                    "example_post": {
                        "subscriptions": ["<sub1>", "<sub2>"],
                        "dataProductIds": ["00000000-0000-0000-0000-000000000002"]
                    },
                    "example_get": "GET ?dataProductId=<guid>&subscriptions=<sub1>,<sub2>"
                }),
                status_code=400,
                mimetype="application/json",
            )

        if not subs:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required 'subscriptions'. Provide in POST JSON, querystring, or set AZURE_SUBSCRIPTIONS app setting.",
                    "hint": "Set AZURE_SUBSCRIPTIONS to a comma-separated list of subscription IDs."
                }),
                status_code=400,
                mimetype="application/json",
            )

        if len(dp_ids_raw) > 500:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Too many dataProductIds in one call ({len(dp_ids_raw)}).",
                    "hint": "Chunk requests from Fabric (e.g., 200 per call)."
                }),
                status_code=400,
                mimetype="application/json",
            )

        dp_ids, invalid = _validate_dp_ids(dp_ids_raw)
        if invalid:
            return func.HttpResponse(
                json.dumps({
                    "error": "One or more dataProductIds are not valid GUIDs.",
                    "invalidDataProductIds": invalid[:50],
                    "hint": "DataProductIds should look like: 00000000-0000-0000-0000-000000000002"
                }),
                status_code=400,
                mimetype="application/json",
            )

        # Build a safe in-list for KQL (GUIDs only, already validated)
        dp_list = ", ".join([f"'{d}'" for d in dp_ids])

        # Query: find resources where tags['dataproductid'] matches any requested id
        # Normalize everything to lowercase (per your standard)
        query = f"""
Resources
| where isnotempty(tags['dataproductid'])
| extend dpId = tolower(tostring(tags['dataproductid']))
| where dpId in~ ({dp_list})
| extend resourceOrigin = tolower(tostring(tags['resource-origin']))
| extend sovereigntyZone = tolower(tostring(tags['sovereignty-zone']))
| project dpId, id, name, type, subscriptionId, resourceGroup, location, resourceOrigin, sovereigntyZone, tags
"""

        rows = _resource_graph_query(subscriptions=subs, query=query)

        # You said there is only one Azure resource per dataproductid.
        # We'll map dpId -> row (first wins).
        matched: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            dp = (r.get("dpId") or "").strip().lower()
            if dp and dp not in matched:
                matched[dp] = r

        missing = [d for d in dp_ids if d not in matched]

        # Build scored results per requested dpId (so Fabric can directly load a scorecard table)
        results: List[Dict[str, Any]] = []
        for d in dp_ids:
            r = matched.get(d)
            if not r:
                score_obj = _score_one(found=False, sovereignty_zone=None, resource_origin=None)
                results.append({
                    "dataProductId": d,
                    "resourceFound": False,
                    "resource": None,
                    "tags": None,
                    "compliance": score_obj,
                })
                continue

            # Extract tag values
            sz = r.get("sovereigntyZone")
            ro = r.get("resourceOrigin")

            score_obj = _score_one(found=True, sovereignty_zone=sz, resource_origin=ro)

            results.append({
                "dataProductId": d,
                "resourceFound": True,
                "resource": {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "type": r.get("type"),
                    "subscriptionId": r.get("subscriptionId"),
                    "resourceGroup": r.get("resourceGroup"),
                    "location": r.get("location"),
                },
                "tags": r.get("tags"),
                "observed": {
                    "sovereignty-zone": (sz or None),
                    "resource-origin": (ro or None),
                },
                "compliance": score_obj,
            })

        return func.HttpResponse(
            json.dumps({
                "requestedCount": len(dp_ids),
                "matchedResourceCount": len(matched),
                "missingCount": len(missing),
                "missingDataProductIds": missing,
                "results": results
            }),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logging.exception("Unhandled error in azure_tag_compliance")
        return func.HttpResponse(
            json.dumps({
                "error": "Unhandled exception",
                "details": str(e)[:2000]
            }),
            status_code=500,
            mimetype="application/json",
        )


# NEW: Residency compliance support (Resource Graph)
# Returns ALL resources + locations for each dataProductId.
# Fabric will do the final scoring using:
#   - dp_dataproductresidency_gold (glossary truth; NULL => Missing)
#   - rs_approved_regions (approved list)
#   - ARG observed location(s) returned by this endpoint
@app.route(route="azure/residencyCompliance", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def azure_residency_compliance(req: func.HttpRequest) -> func.HttpResponse:
    """
    Finds Azure resources by DataProductId using Resource Graph tags.
    Tag keys checked (coalesce):
      - dataproductid (your standard)
      - DataProductID
      - DataProductId

    Accepts:
      POST JSON: { "subscriptions": [...], "dataProductIds": [...] }
      or GET: ?subscriptions=sub1,sub2&dataProductId=<guid>

    Returns per dpId:
      - resourceFound, resourceCount
      - locations (distinct list of region codes)
      - resources (list of resource objects)
    """
    try:
        dp_ids_raw, subs = _parse_inputs(req)

        if not dp_ids_raw:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required 'dataProductIds' (POST JSON) or 'dataProductId' (querystring).",
                    "example_post": {
                        "subscriptions": ["<sub1>", "<sub2>"],
                        "dataProductIds": ["00000000-0000-0000-0000-000000000002"]
                    },
                    "example_get": "GET ?dataProductId=<guid>&subscriptions=<sub1>,<sub2>"
                }),
                status_code=400,
                mimetype="application/json",
            )

        if not subs:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required 'subscriptions'. Provide in POST JSON, querystring, or set AZURE_SUBSCRIPTIONS app setting.",
                    "hint": "Set AZURE_SUBSCRIPTIONS to a comma-separated list of subscription IDs."
                }),
                status_code=400,
                mimetype="application/json",
            )

        if len(dp_ids_raw) > 500:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Too many dataProductIds in one call ({len(dp_ids_raw)}).",
                    "hint": "Chunk requests from Fabric (e.g., 200 per call)."
                }),
                status_code=400,
                mimetype="application/json",
            )

        dp_ids, invalid = _validate_dp_ids(dp_ids_raw)
        if invalid:
            return func.HttpResponse(
                json.dumps({
                    "error": "One or more dataProductIds are not valid GUIDs.",
                    "invalidDataProductIds": invalid[:50],
                    "hint": "DataProductIds should look like: 00000000-0000-0000-0000-000000000002"
                }),
                status_code=400,
                mimetype="application/json",
            )

        dp_list = ", ".join([f"'{d}'" for d in dp_ids])

        # Use coalesce to support common tag-key variants.
        # We normalize dpId to lowercase, then match case-insensitively via in~.
        query = f"""
Resources
| extend dpIdRaw = coalesce(
    tostring(tags['dataproductid']),
    tostring(tags['DataProductID']),
    tostring(tags['DataProductId'])
  )
| extend dpId = tolower(dpIdRaw)
| where isnotempty(dpId)
| where dpId in~ ({dp_list})
| project dpId, id, name, type, subscriptionId, resourceGroup, location
"""

        rows = _resource_graph_query(subscriptions=subs, query=query)

        # Map dpId -> list of resources
        matched: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            dp = (r.get("dpId") or "").strip().lower()
            if not dp:
                continue
            matched.setdefault(dp, []).append(r)

        missing = [d for d in dp_ids if d not in matched]

        results: List[Dict[str, Any]] = []
        for d in dp_ids:
            resources = matched.get(d, [])
            if not resources:
                results.append({
                    "dataProductId": d,
                    "resourceFound": False,
                    "resourceCount": 0,
                    "locations": [],
                    "resources": [],
                    "details": {
                        "note": "No Azure resources found with matching DataProductId tag."
                    }
                })
                continue

            # Build clean resource list + distinct locations
            clean_resources: List[Dict[str, Any]] = []
            locs_set = set()

            for r in resources:
                loc = (r.get("location") or "").strip()
                if loc:
                    locs_set.add(loc.lower())

                clean_resources.append({
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "type": r.get("type"),
                    "subscriptionId": r.get("subscriptionId"),
                    "resourceGroup": r.get("resourceGroup"),
                    "location": r.get("location"),
                })

            results.append({
                "dataProductId": d,
                "resourceFound": True,
                "resourceCount": len(clean_resources),
                "locations": sorted(list(locs_set)),
                "resources": clean_resources,
                "details": {
                    "note": "Use locations[] to compare against glossary residency (after mapping region name -> code).",
                    "matchRuleHint": "For strict residency, require ALL resources to be in the glossary region."
                }
            })

        return func.HttpResponse(
            json.dumps({
                "requestedCount": len(dp_ids),
                "matchedResourceCount": sum(len(v) for v in matched.values()),
                "missingCount": len(missing),
                "missingDataProductIds": missing,
                "results": results
            }),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logging.exception("Unhandled error in azure_residency_compliance")
        return func.HttpResponse(
            json.dumps({
                "error": "Unhandled exception",
                "details": str(e)[:2000]
            }),
            status_code=500,
            mimetype="application/json",
        )


# NEW: Confidential Compute for PII lookup (Resource Graph + ARM VM GET)
# IMPORTANT: auth_level MUST be ANONYMOUS so the Functions runtime does NOT require a function key.
# EasyAuth (Entra) is the gate.
@app.route(route="azure/ccForPiiCompliance", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def azure_cc_for_pii_compliance(req: func.HttpRequest) -> func.HttpResponse:
    """
    Finds the Azure resource by tags['dataproductid'] via Resource Graph.
    Supports Confidential Compute-for-PII checks for:
      - Azure VM (Microsoft.Compute/virtualMachines)
      - Arc machine (Microsoft.HybridCompute/machines)
      - SQL VM (Microsoft.SqlVirtualMachine/sqlVirtualMachines -> linked compute VM)

    Lookup behavior:
      - Azure VM: ARG-first for vmSize/securityType, ARM fallback only if needed
      - Arc machine: ARG model (detectedProperties.model)
      - SQL VM: ARG-first via linked compute VM id, ARM fallback only if needed

    Update assessment behavior:
      - Queries Azure Update Manager assessment summaries from the ARG table `patchassessmentresources`
      - Returns:
          * LastUpdateScanUtc      -> assessment start time (fallback: assessment last modified time)
          * PendingUpdatesTotal    -> summed availablePatchCountByClassification
          * PatchAssessmentStatus  -> Assessed | NoData | null

    Fabric will do the final scoring using rs_confidential_compute_skus.
    Patch fields are informational only and do not change existing CC scoring.
    """
    try:
        dp_ids_raw, subs = _parse_inputs(req)

        if not dp_ids_raw:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required 'dataProductIds' (POST JSON) or 'dataProductId' (querystring).",
                    "example_post": {
                        "subscriptions": ["<sub1>", "<sub2>"],
                        "dataProductIds": ["00000000-0000-0000-0000-000000000002"]
                    },
                    "example_get": "GET ?dataProductId=<guid>&subscriptions=<sub1>,<sub2>"
                }),
                status_code=400,
                mimetype="application/json",
            )

        if not subs:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required 'subscriptions'. Provide in POST JSON, querystring, or set AZURE_SUBSCRIPTIONS app setting.",
                    "hint": "Set AZURE_SUBSCRIPTIONS to a comma-separated list of subscription IDs."
                }),
                status_code=400,
                mimetype="application/json",
            )

        if len(dp_ids_raw) > 500:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Too many dataProductIds in one call ({len(dp_ids_raw)}).",
                    "hint": "Chunk requests from Fabric (e.g., 200 per call)."
                }),
                status_code=400,
                mimetype="application/json",
            )

        dp_ids, invalid = _validate_dp_ids(dp_ids_raw)
        if invalid:
            return func.HttpResponse(
                json.dumps({
                    "error": "One or more dataProductIds are not valid GUIDs.",
                    "invalidDataProductIds": invalid[:50],
                    "hint": "DataProductIds should look like: 00000000-0000-0000-0000-000000000002"
                }),
                status_code=400,
                mimetype="application/json",
            )

        dp_list = ", ".join([f"'{d}'" for d in dp_ids])

        applicable_types = {
            "microsoft.compute/virtualmachines",
            "microsoft.hybridcompute/machines",
            "microsoft.sqlvirtualmachine/sqlvirtualmachines",
        }

        query = f"""
Resources
| where isnotempty(tags['dataproductid'])
| extend dpId = tolower(tostring(tags['dataproductid']))
| where dpId in~ ({dp_list})
| extend p = todynamic(properties)
| extend resourceTypeLc = tolower(type)
| extend isAzureVm = resourceTypeLc == "microsoft.compute/virtualmachines"
| extend isArcMachine = resourceTypeLc == "microsoft.hybridcompute/machines"
| extend isSqlVm = resourceTypeLc == "microsoft.sqlvirtualmachine/sqlvirtualmachines"
| extend vmSizeArg = tostring(p.hardwareProfile.vmSize)
| extend securityTypeArg = tostring(p.securityProfile.securityType)
| extend arcModel = tostring(p.detectedProperties.model)
| extend arcCloudProvider = tostring(p.detectedProperties.cloudprovider)
| extend arcManufacturer = tostring(p.detectedProperties.manufacturer)
| extend arcStatus = tostring(p.status)
| extend arcOsType = tostring(p.osType)
| extend arcOsSku = tostring(p.osSku)
| extend sqlVmLinkedVmResourceId = tostring(p.virtualMachineResourceId)
| project
    dpId, id, name, type, subscriptionId, resourceGroup, location, tags,
    isAzureVm, isArcMachine, isSqlVm,
    vmSizeArg, securityTypeArg,
    arcModel, arcCloudProvider, arcManufacturer, arcStatus, arcOsType, arcOsSku,
    sqlVmLinkedVmResourceId
"""

        rows = _resource_graph_query(subscriptions=subs, query=query)

        matched: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            dp = (r.get("dpId") or "").strip().lower()
            if not dp:
                continue

            r_type = (r.get("type") or "").strip().lower()
            is_cc_applicable = r_type in applicable_types

            if dp not in matched:
                matched[dp] = r
            else:
                existing_type = (matched[dp].get("type") or "").strip().lower()
                existing_is_cc_applicable = existing_type in applicable_types
                if (not existing_is_cc_applicable) and is_cc_applicable:
                    matched[dp] = r

        missing = [d for d in dp_ids if d not in matched]

        sql_vm_linked_ids_lc: List[str] = []
        for r in matched.values():
            r_type = (r.get("type") or "").strip().lower()
            if r_type != "microsoft.sqlvirtualmachine/sqlvirtualmachines":
                continue
            linked_id = str(r.get("sqlVmLinkedVmResourceId") or "").strip()
            if linked_id:
                linked_lc = linked_id.lower()
                if linked_lc not in sql_vm_linked_ids_lc:
                    sql_vm_linked_ids_lc.append(linked_lc)

        linked_vm_arg_by_id: Dict[str, Dict[str, Any]] = {}
        if sql_vm_linked_ids_lc:
            for id_chunk in _chunk_list(sql_vm_linked_ids_lc, 200):
                ids_kql = _kql_in_list(id_chunk)
                linked_query = f"""
Resources
| where tolower(type) == "microsoft.compute/virtualmachines"
| where tolower(id) in~ ({ids_kql})
| extend p = todynamic(properties)
| project
    linkedVmId = tolower(id),
    id, name, type, subscriptionId, resourceGroup, location,
    vmSizeArg = tostring(p.hardwareProfile.vmSize),
    securityTypeArg = tostring(p.securityProfile.securityType)
"""
                linked_rows = _resource_graph_query(subscriptions=subs, query=linked_query)
                for lr in linked_rows:
                    key = (lr.get("linkedVmId") or "").strip().lower()
                    if key and key not in linked_vm_arg_by_id:
                        linked_vm_arg_by_id[key] = lr

        # Build patch assessment lookup targets. For SQL VM we target the linked compute VM.
        patch_target_by_dp: Dict[str, str] = {}
        patch_assessment_ids_lc: List[str] = []
        for d in dp_ids:
            r = matched.get(d)
            if not r:
                continue

            r_type = (r.get("type") or "").strip().lower()
            patch_target_resource_id: Optional[str] = None

            if r_type in {"microsoft.compute/virtualmachines", "microsoft.hybridcompute/machines"}:
                patch_target_resource_id = str(r.get("id") or "").strip() or None
            elif r_type == "microsoft.sqlvirtualmachine/sqlvirtualmachines":
                patch_target_resource_id = str(r.get("sqlVmLinkedVmResourceId") or "").strip() or None

            if not patch_target_resource_id:
                continue

            patch_target_lc = patch_target_resource_id.lower()
            patch_target_by_dp[d] = patch_target_lc
            assessment_id = _assessment_resource_id_for_target_resource(patch_target_resource_id)
            if assessment_id:
                assessment_id_lc = assessment_id.lower()
                if assessment_id_lc not in patch_assessment_ids_lc:
                    patch_assessment_ids_lc.append(assessment_id_lc)

        patch_summary_by_assessment_id: Dict[str, Dict[str, Any]] = {}
        if patch_assessment_ids_lc:
            for id_chunk in _chunk_list(patch_assessment_ids_lc, 200):
                ids_kql = _kql_in_list(id_chunk)
                patch_query = f"""
patchassessmentresources
| where tolower(type) in~ (
    "microsoft.compute/virtualmachines/patchassessmentresults",
    "microsoft.hybridcompute/machines/patchassessmentresults"
)
| where tolower(id) in~ ({ids_kql})
| extend p = todynamic(properties)
| project
    assessmentResourceId = tolower(id),
    assessmentType = type,
    assessmentStartDateTime = tostring(p.startDateTime),
    assessmentLastModifiedDateTime = tostring(p.lastModifiedDateTime),
    availablePatchCountByClassification = p.availablePatchCountByClassification,
    osType = tostring(p.osType),
    rebootPending = tostring(p.rebootPending),
    patchServiceUsed = tostring(p.patchServiceUsed),
    errorDetails = p.errorDetails
"""
                patch_rows = _resource_graph_query(subscriptions=subs, query=patch_query)
                for pr in patch_rows:
                    key = (pr.get("assessmentResourceId") or "").strip().lower()
                    if key and key not in patch_summary_by_assessment_id:
                        patch_summary_by_assessment_id[key] = pr

        results: List[Dict[str, Any]] = []
        for d in dp_ids:
            r = matched.get(d)
            if not r:
                results.append({
                    "dataProductId": d,
                    "resourceFound": False,
                    "vmApplicable": None,
                    "ccResourceKind": None,
                    "ccLookupSku": None,
                    "ccLookupSkuSource": None,
                    "LastUpdateScanUtc": None,
                    "PendingUpdatesTotal": None,
                    "PatchAssessmentStatus": None,
                    "resource": None,
                    "vm": None,
                    "arc": None,
                    "details": {
                        "note": "No Azure resource found with tags['dataproductid'] matching this DataProductId."
                    }
                })
                continue

            resource_obj = {
                "id": r.get("id"),
                "name": r.get("name"),
                "type": r.get("type"),
                "subscriptionId": r.get("subscriptionId"),
                "resourceGroup": r.get("resourceGroup"),
                "location": r.get("location"),
            }

            r_type = (r.get("type") or "").strip().lower()
            is_azure_vm = (r_type == "microsoft.compute/virtualmachines")
            is_arc_machine = (r_type == "microsoft.hybridcompute/machines")
            is_sql_vm = (r_type == "microsoft.sqlvirtualmachine/sqlvirtualmachines")

            patch_target_id_lc = patch_target_by_dp.get(d)
            patch_assessment_id_lc = _assessment_resource_id_for_target_resource(patch_target_id_lc).lower() if patch_target_id_lc else None
            patch_summary = patch_summary_by_assessment_id.get(patch_assessment_id_lc) if patch_assessment_id_lc else None
            last_update_scan_utc = None
            pending_updates_total = None
            patch_assessment_status = None

            if patch_summary:
                last_update_scan_utc = (
                    patch_summary.get("assessmentStartDateTime")
                    or patch_summary.get("assessmentLastModifiedDateTime")
                )
                pending_updates_total = _sum_patch_counts(
                    patch_summary.get("availablePatchCountByClassification")
                )
                patch_assessment_status = "Assessed"
            elif patch_target_id_lc:
                patch_assessment_status = "NoData"

            if not (is_azure_vm or is_arc_machine or is_sql_vm):
                results.append({
                    "dataProductId": d,
                    "resourceFound": True,
                    "vmApplicable": False,
                    "ccResourceKind": "NotApplicable",
                    "ccLookupSku": None,
                    "ccLookupSkuSource": None,
                    "LastUpdateScanUtc": None,
                    "PendingUpdatesTotal": None,
                    "PatchAssessmentStatus": None,
                    "resource": resource_obj,
                    "vm": None,
                    "arc": None,
                    "details": {
                        "note": "Resource found but it is not an Azure VM, Arc machine, or SQL VM. Treat as N/A for Confidential Compute scoring.",
                        "resourceTypeObserved": r.get("type")
                    }
                })
                continue

            if is_arc_machine:
                arc_model = str(r.get("arcModel")).strip() if r.get("arcModel") is not None else None
                arc_cloud = str(r.get("arcCloudProvider")).strip() if r.get("arcCloudProvider") is not None else None
                arc_mfr = str(r.get("arcManufacturer")).strip() if r.get("arcManufacturer") is not None else None
                arc_status = str(r.get("arcStatus")).strip() if r.get("arcStatus") is not None else None
                arc_os_type = str(r.get("arcOsType")).strip() if r.get("arcOsType") is not None else None
                arc_os_sku = str(r.get("arcOsSku")).strip() if r.get("arcOsSku") is not None else None

                results.append({
                    "dataProductId": d,
                    "resourceFound": True,
                    "vmApplicable": True,
                    "ccResourceKind": "ArcMachine",
                    "ccLookupSku": arc_model,
                    "ccLookupSkuSource": "ARG.properties.detectedProperties.model",
                    "LastUpdateScanUtc": last_update_scan_utc,
                    "PendingUpdatesTotal": pending_updates_total,
                    "PatchAssessmentStatus": patch_assessment_status,
                    "resource": resource_obj,
                    "vm": None,
                    "arc": {
                        "model": arc_model,
                        "cloudProvider": arc_cloud,
                        "manufacturer": arc_mfr,
                        "status": arc_status,
                        "osType": arc_os_type,
                        "osSku": arc_os_sku
                    },
                    "details": {
                        "note": "Arc machine details returned from ARG. Use ccLookupSku (Arc model) + resource.location in Fabric to score against rulesets. Patch assessment is sourced from Azure Update Manager / ARG when available.",
                    }
                })
                continue

            if is_azure_vm:
                arg_vm_size = str(r.get("vmSizeArg") or "").strip() or None
                arg_security_type = str(r.get("securityTypeArg") or "").strip() or None

                if arg_vm_size:
                    results.append({
                        "dataProductId": d,
                        "resourceFound": True,
                        "vmApplicable": True,
                        "ccResourceKind": "AzureVM",
                        "ccLookupSku": arg_vm_size,
                        "ccLookupSkuSource": "ARG.properties.hardwareProfile.vmSize",
                        "LastUpdateScanUtc": last_update_scan_utc,
                        "PendingUpdatesTotal": pending_updates_total,
                        "PatchAssessmentStatus": patch_assessment_status,
                        "resource": resource_obj,
                        "vm": {
                            "vmSize": arg_vm_size,
                            "securityType": arg_security_type,
                            "securityProfile": None
                        },
                        "arc": None,
                        "details": {
                            "note": "VM details returned from ARG. Use ccLookupSku (VM size) + resource.location in Fabric to score against rulesets. Patch assessment is sourced from Azure Update Manager / ARG when available."
                        }
                    })
                    continue

                sub_id = r.get("subscriptionId")
                rg = r.get("resourceGroup")
                vm_name = r.get("name")
                vm_api_version = os.getenv("VM_API_VERSION", "2024-03-01")
                vm_url = (
                    f"https://management.azure.com/subscriptions/{sub_id}"
                    f"/resourceGroups/{rg}"
                    f"/providers/Microsoft.Compute/virtualMachines/{vm_name}"
                    f"?api-version={vm_api_version}"
                )

                try:
                    vm_json = _arm_get_json(vm_url)
                    props = (vm_json.get("properties") or {})
                    hardware = (props.get("hardwareProfile") or {})
                    vm_size = hardware.get("vmSize")
                    security_profile = props.get("securityProfile") or None
                    security_type = None
                    if isinstance(security_profile, dict):
                        security_type = security_profile.get("securityType")

                    results.append({
                        "dataProductId": d,
                        "resourceFound": True,
                        "vmApplicable": True,
                        "ccResourceKind": "AzureVM",
                        "ccLookupSku": vm_size,
                        "ccLookupSkuSource": "ARM.properties.hardwareProfile.vmSize",
                        "LastUpdateScanUtc": last_update_scan_utc,
                        "PendingUpdatesTotal": pending_updates_total,
                        "PatchAssessmentStatus": patch_assessment_status,
                        "resource": resource_obj,
                        "vm": {
                            "vmSize": vm_size,
                            "securityType": security_type,
                            "securityProfile": security_profile
                        },
                        "arc": None,
                        "details": {
                            "note": "VM details returned from ARM (ARG fallback path). Use ccLookupSku (VM size) + resource.location in Fabric to score against rulesets. Patch assessment is sourced from Azure Update Manager / ARG when available."
                        }
                    })
                except Exception as arm_err:
                    results.append({
                        "dataProductId": d,
                        "resourceFound": True,
                        "vmApplicable": True,
                        "ccResourceKind": "AzureVM",
                        "ccLookupSku": None,
                        "ccLookupSkuSource": "ARM.properties.hardwareProfile.vmSize",
                        "LastUpdateScanUtc": last_update_scan_utc,
                        "PendingUpdatesTotal": pending_updates_total,
                        "PatchAssessmentStatus": patch_assessment_status,
                        "resource": resource_obj,
                        "vm": None,
                        "arc": None,
                        "details": {
                            "note": "VM found via Resource Graph, but failed to read VM details from ARM.",
                            "armError": str(arm_err)[:2000]
                        }
                    })
                continue

            # SQL VM path (linked compute VM details via ARG-first, ARM fallback).
            # Patching data is still assessed from the linked compute VM because Update Manager
            # assessment records are exposed for compute/Arc machine resources, not SQL VM wrapper resources.
            linked_vm_id = str(r.get("sqlVmLinkedVmResourceId") or "").strip() or None
            linked_vm_id_lc = linked_vm_id.lower() if linked_vm_id else None
            linked_arg = linked_vm_arg_by_id.get(linked_vm_id_lc) if linked_vm_id_lc else None

            if linked_arg:
                linked_vm_size = str(linked_arg.get("vmSizeArg") or "").strip() or None
                linked_security_type = str(linked_arg.get("securityTypeArg") or "").strip() or None
                if linked_vm_size:
                    results.append({
                        "dataProductId": d,
                        "resourceFound": True,
                        "vmApplicable": True,
                        "ccResourceKind": "SqlVirtualMachine",
                        "ccLookupSku": linked_vm_size,
                        "ccLookupSkuSource": "ARG(linked VM).properties.hardwareProfile.vmSize",
                        "LastUpdateScanUtc": last_update_scan_utc,
                        "PendingUpdatesTotal": pending_updates_total,
                        "PatchAssessmentStatus": patch_assessment_status,
                        "resource": resource_obj,
                        "vm": {
                            "vmSize": linked_vm_size,
                            "securityType": linked_security_type,
                            "securityProfile": None,
                            "linkedComputeVmResourceId": linked_vm_id,
                        },
                        "arc": None,
                        "details": {
                            "note": "SQL VM found. Linked compute VM details returned from ARG. Use ccLookupSku (VM size) + resource.location in Fabric to score against rulesets. Patch assessment is sourced from the linked compute VM when available.",
                            "sqlVmLinkedVmResourceId": linked_vm_id
                        }
                    })
                    continue

            if not linked_vm_id:
                results.append({
                    "dataProductId": d,
                    "resourceFound": True,
                    "vmApplicable": True,
                    "ccResourceKind": "SqlVirtualMachine",
                    "ccLookupSku": None,
                    "ccLookupSkuSource": "ARG/ARM linked VM lookup",
                    "LastUpdateScanUtc": None,
                    "PendingUpdatesTotal": None,
                    "PatchAssessmentStatus": None,
                    "resource": resource_obj,
                    "vm": None,
                    "arc": None,
                    "details": {
                        "note": "SQL VM resource found, but linked compute VM resource id was empty in properties.virtualMachineResourceId."
                    }
                })
                continue

            try:
                vm_api_version = os.getenv("VM_API_VERSION", "2024-03-01")
                vm_url = f"https://management.azure.com{linked_vm_id}?api-version={vm_api_version}"
                vm_json = _arm_get_json(vm_url)
                props = (vm_json.get("properties") or {})
                hardware = (props.get("hardwareProfile") or {})
                vm_size = hardware.get("vmSize")
                security_profile = props.get("securityProfile") or None
                security_type = None
                if isinstance(security_profile, dict):
                    security_type = security_profile.get("securityType")

                results.append({
                    "dataProductId": d,
                    "resourceFound": True,
                    "vmApplicable": True,
                    "ccResourceKind": "SqlVirtualMachine",
                    "ccLookupSku": vm_size,
                    "ccLookupSkuSource": "ARM(linked VM).properties.hardwareProfile.vmSize",
                    "LastUpdateScanUtc": last_update_scan_utc,
                    "PendingUpdatesTotal": pending_updates_total,
                    "PatchAssessmentStatus": patch_assessment_status,
                    "resource": resource_obj,
                    "vm": {
                        "vmSize": vm_size,
                        "securityType": security_type,
                        "securityProfile": security_profile,
                        "linkedComputeVmResourceId": linked_vm_id,
                    },
                    "arc": None,
                    "details": {
                        "note": "SQL VM found. Linked compute VM details returned from ARM (ARG fallback path). Use ccLookupSku (VM size) + resource.location in Fabric to score against rulesets. Patch assessment is sourced from the linked compute VM when available.",
                        "sqlVmLinkedVmResourceId": linked_vm_id
                    }
                })
            except Exception as arm_err:
                results.append({
                    "dataProductId": d,
                    "resourceFound": True,
                    "vmApplicable": True,
                    "ccResourceKind": "SqlVirtualMachine",
                    "ccLookupSku": None,
                    "ccLookupSkuSource": "ARM(linked VM).properties.hardwareProfile.vmSize",
                    "LastUpdateScanUtc": last_update_scan_utc,
                    "PendingUpdatesTotal": pending_updates_total,
                    "PatchAssessmentStatus": patch_assessment_status,
                    "resource": resource_obj,
                    "vm": None,
                    "arc": None,
                    "details": {
                        "note": "SQL VM found via Resource Graph, but failed to read linked compute VM details from ARG/ARM.",
                        "sqlVmLinkedVmResourceId": linked_vm_id,
                        "armError": str(arm_err)[:2000]
                    }
                })

        return func.HttpResponse(
            json.dumps({
                "requestedCount": len(dp_ids),
                "matchedResourceCount": len(matched),
                "missingCount": len(missing),
                "missingDataProductIds": missing,
                "results": results
            }),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logging.exception("Unhandled error in azure_cc_for_pii_compliance")
        return func.HttpResponse(
            json.dumps({
                "error": "Unhandled exception",
                "details": str(e)[:2000]
            }),
            status_code=500,
            mimetype="application/json",
        )

# NEW: Defender compliance check (Resource Graph - resources + securityresources)
# - Compute: accepts VirtualMachines (Defender for Servers) or SqlServerVirtualMachines (SQL VM plan)
# - SQL: accepts SqlServers or SqlServerVirtualMachines
# - Storage: accepts StorageAccounts
# - Fabric / unknown types: N/A => 100
# Scoring rubric:
#   0%   Couldn't find the resource
#   25%  Found the resource but Defender not configured
#   50%  Found the resource + Defender configured but not running (no assessments)
#   75%  Found the resource + Defender running but has critical alerts (Active+High)
#   100% Found the resource + Defender running without critical alerts
#   N/A  If Defender cannot be configured, it is 100%
# CC/PII investigate tag apply (generic tag write via ARM, supports cross-tenant subscriptions)
# This endpoint is intended to be called AFTER the Copilot topic asks the user to confirm.
@app.route(route="azure/ccPiiInvestigateTagApply", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def azure_cc_pii_investigate_tag_apply(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = _try_get_json(req)
        dry_run = _to_bool(body.get("dryRun"), default=True)
        confirm = _to_bool(body.get("confirm"), default=False)

        source = (body.get("source") or "CopilotStudio").strip()
        actor = (body.get("actor") or "").strip() or None
        request_id = (body.get("requestId") or "").strip() or None

        # Accept either {items:[...]} or a single object payload
        items = body.get("items")
        if not items:
            # If resourceId is present, treat whole body as a single item
            if body.get("resourceId") or body.get("ResourceId"):
                items = [body]
            else:
                items = []

        if not items:
            return _json_http(
                {
                    "error": "No items provided.",
                    "hint": "POST JSON must include either items:[{resourceId, tagKey, tagValue, ...}] or a single object with resourceId.",
                    "example": {
                        "dryRun": True,
                        "confirm": False,
                        "source": "CopilotStudio",
                        "actor": "<optional>",
                        "requestId": "ccpii-investigate-001",
                        "items": [
                            {
                                "dataProductId": "<guid>",
                                "dataProductDisplayName": "<name>",
                                "ccScorePct": 50,
                                "ownerEmail": "owner@example.com",
                                "resourceId": "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Compute/virtualMachines/<vm>",
                                "tagKey": "compliance-status",
                                "tagValue": "investigate"
                            }
                        ]
                    },
                },
                status_code=400,
            )

        # Hard confirmation required for real write
        if (not dry_run) and (not confirm):
            return _json_http(
                {
                    "error": "Missing confirmation. For a real write, send confirm=true and dryRun=false.",
                    "hint": "Keep dryRun=true if you only want to validate the payload.",
                },
                status_code=400,
            )

        results: List[Dict[str, Any]] = []
        applied_count = 0
        error_count = 0

        for it in items:
            resource_id = (it.get("resourceId") or it.get("ResourceId") or "").strip()
            if not resource_id:
                error_count += 1
                results.append({"status": "error", "error": "Missing resourceId in item.", "item": it})
                continue

            dp_id = (it.get("dataProductId") or it.get("DataProductId") or it.get("DataProductID") or "").strip() or None
            dp_name = (it.get("dataProductDisplayName") or it.get("DataProductDisplayName") or "").strip() or None
            owner_email = (it.get("ownerEmail") or it.get("OwnerEmail") or "").strip() or None

            # Allow both naming styles (tagKey/tagValue or SuggestedTagKey/SuggestedTagValue from your model)
            tag_key = (it.get("tagKey") or it.get("SuggestedTagKey") or it.get("suggestedTagKey") or "compliance-status").strip()
            tag_value = (it.get("tagValue") or it.get("SuggestedTagValue") or it.get("suggestedTagValue") or "investigate").strip()

            cc_score_pct_raw = it.get("ccScorePct") or it.get("CCScorePct")
            try:
                cc_score_pct = int(cc_score_pct_raw) if cc_score_pct_raw is not None and str(cc_score_pct_raw).strip() != "" else None
            except Exception:
                cc_score_pct = None

            try:
                merge_out = _arm_merge_tags(resource_id, {tag_key: tag_value}, dry_run=dry_run)

                status = "preview" if dry_run else "applied"
                notes = []
                if dry_run:
                    notes.append("Dry run only. No tags were written.")
                else:
                    notes.append("Investigate tag applied via Microsoft.Resources/tags/default (merged with existing tags).")

                # Emit changelog record (best effort)
                log_record = _build_cc_changelog_record(
                    data_product_id=dp_id,
                    data_product_name=dp_name,
                    cc_score_pct=cc_score_pct,
                    owner_email=owner_email,
                    resource_id=resource_id,
                    tag_key=tag_key,
                    tag_value=tag_value,
                    status=status,
                    dry_run=dry_run,
                    source=source,
                    actor=actor,
                    request_id=request_id,
                    notes=notes,
                    raw_action_payload={
                        "mergeResult": merge_out,
                        "item": it,
                    },
                )
                _emit_action_log_stub(log_record)

                results.append({
                    "resourceId": resource_id,
                    "dataProductId": dp_id,
                    "dataProductDisplayName": dp_name,
                    "ownerEmail": owner_email,
                    "ccScorePct": cc_score_pct,
                    "tagKey": tag_key,
                    "tagValue": tag_value,
                    "dryRun": dry_run,
                    "applied": bool(merge_out.get("applied")),
                    "beforeTags": merge_out.get("before"),
                    "afterTags": merge_out.get("after"),
                    "status": status,
                })
                if not dry_run:
                    applied_count += 1

            except Exception as ex:
                error_count += 1
                log_record = _build_cc_changelog_record(
                    data_product_id=dp_id,
                    data_product_name=dp_name,
                    cc_score_pct=cc_score_pct,
                    owner_email=owner_email,
                    resource_id=resource_id,
                    tag_key=tag_key,
                    tag_value=tag_value,
                    status="error",
                    dry_run=dry_run,
                    source=source,
                    actor=actor,
                    request_id=request_id,
                    notes=[f"Failed to apply tag: {str(ex)[:500]}"],
                    raw_action_payload={"item": it},
                )
                _emit_action_log_stub(log_record)

                results.append({
                    "resourceId": resource_id,
                    "dataProductId": dp_id,
                    "dataProductDisplayName": dp_name,
                    "error": str(ex)[:2000],
                    "status": "error",
                })

        return _json_http(
            {
                "ok": True,
                "dryRun": dry_run,
                "confirm": confirm,
                "requestedCount": len(items),
                "appliedCount": applied_count,
                "errorCount": error_count,
                "results": results,
            },
            status_code=200 if error_count == 0 else 207,  # 207 = multi-status
        )

    except Exception as e:
        logging.exception("Unhandled error in azure_cc_pii_investigate_tag_apply")
        return _json_http(
            {"error": "Unhandled exception", "details": str(e)[:2000]},
            status_code=500,
        )

@app.route(route="azure/defenderCompliance", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def azure_defender_compliance(req: func.HttpRequest) -> func.HttpResponse:
    try:
        dp_ids_raw, subs = _parse_inputs(req)
        na_dp_ids = set(_parse_na_dp_ids(req))

        if not dp_ids_raw:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required 'dataProductIds' (POST JSON) or 'dataProductId' (querystring).",
                    "example_post": {
                        "subscriptions": ["<sub1>", "<sub2>"],
                        "dataProductIds": ["00000000-0000-0000-0000-000000000002"],
                        "naDataProductIds": ["<optional_fabric_dp_guid>"]
                    },
                    "example_get": "GET ?dataProductId=<guid>&subscriptions=<sub1>,<sub2>&naDataProductIds=<guid1>,<guid2>"
                }),
                status_code=400,
                mimetype="application/json",
            )

        if not subs:
            return func.HttpResponse(
                json.dumps({
                    "error": "Missing required 'subscriptions'. Provide in POST JSON, querystring, or set AZURE_SUBSCRIPTIONS app setting.",
                    "hint": "Set AZURE_SUBSCRIPTIONS to a comma-separated list of subscription IDs."
                }),
                status_code=400,
                mimetype="application/json",
            )

        if len(dp_ids_raw) > 500:
            return func.HttpResponse(
                json.dumps({
                    "error": f"Too many dataProductIds in one call ({len(dp_ids_raw)}).",
                    "hint": "Chunk requests from Fabric (e.g., 200 per call)."
                }),
                status_code=400,
                mimetype="application/json",
            )

        dp_ids, invalid = _validate_dp_ids(dp_ids_raw)
        if invalid:
            return func.HttpResponse(
                json.dumps({
                    "error": "One or more dataProductIds are not valid GUIDs.",
                    "invalidDataProductIds": invalid[:50],
                    "hint": "DataProductIds should look like: 00000000-0000-0000-0000-000000000002"
                }),
                status_code=400,
                mimetype="application/json",
            )

        dp_list = _kql_in_list(dp_ids)

        # 1) Find Azure resources tied to each DataProductId (tag variants supported)
        resources_query = f"""
Resources
| extend dpIdRaw = coalesce(
    tostring(tags['dataproductid']),
    tostring(tags['DataProductID']),
    tostring(tags['DataProductId'])
  )
| extend dpId = tolower(dpIdRaw)
| where isnotempty(dpId)
| where dpId in~ ({dp_list})
| project dpId, id, name, type, subscriptionId, resourceGroup, location
"""
        rows = _resource_graph_query(subscriptions=subs, query=resources_query)

        matched: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            dp = (r.get("dpId") or "").strip().lower()
            if not dp:
                continue
            matched.setdefault(dp, []).append(r)

        missing = [d for d in dp_ids if d not in matched]

        # Build a list of applicable resourceIds + subscriptionIds for downstream securityresources queries
        applicable_resource_ids: List[str] = []
        applicable_sub_ids: set = set()

        # Also keep per-dp cleaned resources now, because we’ll reuse
        dp_resources_clean: Dict[str, List[Dict[str, Any]]] = {}
        for d in dp_ids:
            resources = matched.get(d, [])
            clean: List[Dict[str, Any]] = []
            for r in resources:
                rid = (r.get("id") or "").strip()
                rtype = (r.get("type") or "").strip()
                subid = (r.get("subscriptionId") or "").strip()
                plans = _defender_candidate_plans_for_resource_type(rtype)
                is_applicable = len(plans) > 0

                if is_applicable and rid:
                    applicable_resource_ids.append(rid.lower())
                if is_applicable and subid:
                    applicable_sub_ids.add(subid)

                clean.append({
                    "id": rid,
                    "name": r.get("name"),
                    "type": rtype,
                    "subscriptionId": subid,
                    "resourceGroup": r.get("resourceGroup"),
                    "location": r.get("location"),
                    "defenderCandidatePlans": plans,
                    "defenderApplicable": is_applicable,
                    "defenderNonApplicableReason": (
                        "Non-configurable type (e.g., Fabric/PowerBI)" if _is_non_applicable_type(rtype)
                        else ("Out of scope / cannot configure" if not is_applicable else None)
                    )
                })
            dp_resources_clean[d] = clean

        # 2) Pull Defender pricing tiers (configured) for relevant plans at subscription scope
        pricing_map: Dict[str, Dict[str, str]] = {}  # subId -> plan(lower) -> tier
        if applicable_sub_ids:
            plans_list = _kql_in_list(sorted(list(DEFENDER_PLANS)))
            sub_list = _kql_in_list(sorted(list(applicable_sub_ids)))

            pricings_query = f"""
securityresources
| where type =~ "microsoft.security/pricings"
| extend subId = tostring(split(id, "/")[2])
| extend plan = tolower(name)
| where subId in~ ({sub_list})
| where plan in~ ({plans_list})
| extend pricingTier = tostring(properties.pricingTier)
| project subId, plan, pricingTier
"""
            pricing_rows = _resource_graph_query(subscriptions=subs, query=pricings_query)
            for pr in pricing_rows:
                subid = (pr.get("subId") or "").strip()
                plan = (pr.get("plan") or "").strip().lower()
                tier = (pr.get("pricingTier") or "").strip()
                if not subid or not plan:
                    continue
                pricing_map.setdefault(subid, {})[plan] = tier

        # 3) Pull assessments for applicable resources (running signal)
        assessments_by_resource: Dict[str, Dict[str, Any]] = {}  # rid(lower) -> counts + samples
        if applicable_resource_ids:
            # Chunk to keep KQL manageable
            for chunk in _chunk_list(sorted(list(set(applicable_resource_ids))), 200):
                rid_list = _kql_in_list(chunk)
                assessments_query = f"""
securityresources
| where type =~ "microsoft.security/assessments"
| extend assessedResourceId = tolower(tostring(coalesce(properties.resourceDetails.Id, properties.resourceDetails.id)))
| where isnotempty(assessedResourceId)
| where assessedResourceId in~ ({rid_list})
| extend statusCode = tostring(properties.status.code)
| extend displayName = tostring(properties.displayName)
| extend firstEvaluationDate = tostring(properties.status.firstEvaluationDate)
| extend statusChangeDate = tostring(properties.status.statusChangeDate)
| project assessedResourceId, statusCode, displayName, firstEvaluationDate, statusChangeDate
"""
                a_rows = _resource_graph_query(subscriptions=subs, query=assessments_query)
                for a in a_rows:
                    rid = (a.get("assessedResourceId") or "").strip().lower()
                    if not rid:
                        continue
                    status = (a.get("statusCode") or "").strip()
                    obj = assessments_by_resource.setdefault(rid, {
                        "total": 0,
                        "healthy": 0,
                        "unhealthy": 0,
                        "notApplicable": 0,
                        "unknown": 0,
                        "sample": [],
                    })
                    obj["total"] += 1
                    if status.lower() == "healthy":
                        obj["healthy"] += 1
                    elif status.lower() == "unhealthy":
                        obj["unhealthy"] += 1
                    elif status.lower() == "notapplicable":
                        obj["notApplicable"] += 1
                    elif status:
                        obj["unknown"] += 1
                    else:
                        obj["unknown"] += 1

                    if len(obj["sample"]) < 5:
                        obj["sample"].append({
                            "displayName": a.get("displayName"),
                            "statusCode": status,
                            "firstEvaluationDate": a.get("firstEvaluationDate"),
                            "statusChangeDate": a.get("statusChangeDate"),
                        })

        # 4) Pull High + Active alerts for applicable resources (critical alerts)
        alerts_by_resource: Dict[str, Dict[str, Any]] = {}  # rid(lower) -> count + sample
        if applicable_resource_ids:
            for chunk in _chunk_list(sorted(list(set(applicable_resource_ids))), 200):
                rid_list = _kql_in_list(chunk)
                alerts_query = f"""
securityresources
| where type =~ "microsoft.security/locations/alerts"
| where tostring(properties.Status) =~ "Active"
| where tostring(properties.Severity) =~ "High"
| extend affectedResourceId = tolower(tostring(properties.ResourceIdentifiers.azureResourceId))
| where isnotempty(affectedResourceId)
| where affectedResourceId in~ ({rid_list})
| project affectedResourceId,
          alertType = tostring(properties.AlertType),
          systemAlertId = tostring(properties.SystemAlertId),
          severity = tostring(properties.Severity),
          status = tostring(properties.Status),
          startTimeUtc = tostring(properties.StartTimeUtc)
"""
                al_rows = _resource_graph_query(subscriptions=subs, query=alerts_query)
                for al in al_rows:
                    rid = (al.get("affectedResourceId") or "").strip().lower()
                    if not rid:
                        continue
                    obj = alerts_by_resource.setdefault(rid, {"highActiveCount": 0, "sample": []})
                    obj["highActiveCount"] += 1
                    if len(obj["sample"]) < 5:
                        obj["sample"].append({
                            "alertType": al.get("alertType"),
                            "systemAlertId": al.get("systemAlertId"),
                            "severity": al.get("severity"),
                            "status": al.get("status"),
                            "startTimeUtc": al.get("startTimeUtc"),
                        })

        # 5) Build results per dpId with rubric scoring
        results: List[Dict[str, Any]] = []

        for d in dp_ids:
            # Explicit N/A override (e.g., Fabric DP id)
            if d in na_dp_ids:
                results.append({
                    "dataProductId": d,
                    "resourceFound": False,
                    "applicable": False,
                    "progressScore": 100,
                    "progressState": "notApplicableOverride",
                    "details": {
                        "note": "Caller marked this data product as N/A for Defender check.",
                    },
                    "resources": [],
                })
                continue

            resources = dp_resources_clean.get(d, [])

            if not resources:
                results.append({
                    "dataProductId": d,
                    "resourceFound": False,
                    "applicable": None,
                    "progressScore": 0,
                    "progressState": "resourceNotFound",
                    "details": {
                        "note": "No Azure resources found with matching DataProductId tag."
                    },
                    "resources": [],
                })
                continue

            # Determine applicability (VM/SQL/Storage in scope)
            applicable_resources = [r for r in resources if r.get("defenderApplicable")]
            if not applicable_resources:
                # Resource exists, but all are out of scope / non-configurable => N/A = 100
                results.append({
                    "dataProductId": d,
                    "resourceFound": True,
                    "applicable": False,
                    "progressScore": 100,
                    "progressState": "notApplicable",
                    "details": {
                        "note": "Resources found, but none are applicable for Defender plans (treated as N/A => 100)."
                    },
                    "resources": resources,
                })
                continue

            # Per-resource evaluation
            configured_ok_count = 0
            running_ok_count = 0
            high_alerts_total = 0
            any_unhealthy_assessments = False

            per_resource_eval: List[Dict[str, Any]] = []
            for r in applicable_resources:
                rid = (r.get("id") or "").strip().lower()
                subid = (r.get("subscriptionId") or "").strip()
                plans = r.get("defenderCandidatePlans") or []

                # Plan configured if ANY candidate plan is Standard
                plan_tiers = {}
                configured = False
                for p in plans:
                    tier = (pricing_map.get(subid, {}).get(p) or "")
                    plan_tiers[p] = tier or None
                    if tier.strip().lower() == "standard":
                        configured = True

                if configured:
                    configured_ok_count += 1

                a = assessments_by_resource.get(rid, None)
                assessment_total = int((a or {}).get("total") or 0)
                unhealthy_count = int((a or {}).get("unhealthy") or 0)
                healthy_count = int((a or {}).get("healthy") or 0)
                has_assessments = assessment_total > 0
                running = configured and has_assessments

                if running:
                    running_ok_count += 1

                if unhealthy_count > 0:
                    any_unhealthy_assessments = True

                al = alerts_by_resource.get(rid, None)
                high_active = int(al.get("highActiveCount", 0)) if al else 0
                high_alerts_total += high_active

                per_resource_eval.append({
                    "resource": {
                        "id": r.get("id"),
                        "name": r.get("name"),
                        "type": r.get("type"),
                        "subscriptionId": r.get("subscriptionId"),
                        "resourceGroup": r.get("resourceGroup"),
                        "location": r.get("location"),
                    },
                    "candidatePlans": plans,
                    "planTiers": plan_tiers,
                    "defenderConfigured": configured,
                    "hasAssessments": has_assessments,
                    "defenderRunning": running,
                    "assessmentsSummary": a,
                    "highActiveAlerts": high_active,
                    "alertsSample": (al.get("sample") if al else []),
                })

            applicable_count = len(applicable_resources)
            has_critical_alerts = high_alerts_total > 0

            # Rubric scoring
            # 0   = handled earlier when resource not found
            # 25  = found applicable resource(s) but Defender not configured
            # 50  = Defender configured but unhealthy assessments exist
            #       OR configured but not yet running / no assessments returned
            # 75  = Defender running with no unhealthy assessments, but active critical alert(s) exist
            # 100 = Defender running with no unhealthy assessments and no active critical alert(s)
            if configured_ok_count <= 0:
                progress_score = 25
                progress_state = "notConfigured"
            elif any_unhealthy_assessments:
                progress_score = 50
                progress_state = "assessmentUnhealthy"
            elif running_ok_count <= 0:
                progress_score = 50
                progress_state = "configuredNotRunning"
            elif has_critical_alerts:
                progress_score = 75
                progress_state = "runningHealthyWithCriticalAlert"
            else:
                progress_score = 100
                progress_state = "runningHealthy"

            results.append({
                "dataProductId": d,
                "resourceFound": True,
                "applicable": True,
                "progressScore": progress_score,
                "progressState": progress_state,
                "rollup": {
                    "applicableResourceCount": applicable_count,
                    "configuredResourceCount": configured_ok_count,
                    "runningResourceCount": running_ok_count,
                    "highActiveAlertCount": high_alerts_total,
                    "hasUnhealthyAssessments": any_unhealthy_assessments,
                    "note": "Running is inferred from presence of Defender assessments. Critical alerts = Active + High Defender alerts."
                },
                "resources": resources,          # full list (incl. non-applicable)
                "evaluatedResources": per_resource_eval,  # applicable only
                "pricingObserved": pricing_map,  # useful for debugging; Fabric can ignore
            })

        return func.HttpResponse(
            json.dumps({
                "requestedCount": len(dp_ids),
                "matchedResourceCount": sum(len(v) for v in matched.values()),
                "missingCount": len(missing),
                "missingDataProductIds": missing,
                "results": results
            }),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logging.exception("Unhandled error in azure_defender_compliance")
        return func.HttpResponse(
            json.dumps({
                "error": "Unhandled exception",
                "details": str(e)[:2000]
            }),
            status_code=500,
            mimetype="application/json",
        )


# -----------------------------
# AWS S3 Residency Compliance (Lean test endpoint)
# -----------------------------
def _aws_client(service_name: str, region: Optional[str] = None):
    """
    Create a boto3 client using env var credentials (fast test path).
    Required App Settings:
      - AWS_ACCESS_KEY_ID
      - AWS_SECRET_ACCESS_KEY
    Optional:
      - AWS_SESSION_TOKEN
      - AWS_REGION (default region fallback)
    """
    aws_region = (region or os.getenv("AWS_REGION") or "us-east-1").strip()
    return boto3.client(
        service_name,
        region_name=aws_region,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN") or None,
    )

def _parse_s3_bucket_from_arn(bucket_arn: str) -> Optional[str]:
    """
    Supports ARN formats like:
      arn:aws:s3:::bucket-name
    """
    arn = (bucket_arn or "").strip()
    if not arn:
        return None
    # S3 bucket ARN ends with :::bucket-name
    m = re.match(r"^arn:aws:s3:::(?P<bucket>[a-zA-Z0-9.\-_]{3,63})$", arn)
    if m:
        return m.group("bucket")
    return None

def _normalize_s3_bucket_location(loc: Any) -> str:
    """
    S3 get_bucket_location returns:
      - None or 'US' for us-east-1
      - 'eu-west-1', etc for others
    """
    if loc is None:
        return "us-east-1"
    s = str(loc).strip()
    if s == "" or s.upper() == "US":
        return "us-east-1"
    return s

@app.route(route="azure/residencyComplianceAws", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def azure_residency_compliance_aws(req: func.HttpRequest) -> func.HttpResponse:
    """
    LEAN TEST ENDPOINT:
    Proves the Function App can read AWS S3 bucket tags + bucket region.

    Accepts:
      GET:
        ?bucketName=s3-example-bucket
        or ?bucketArn=arn:aws:s3:::s3-example-bucket
        optional: ?region=us-east-1  (only used for AWS API endpoint selection)
      POST JSON:
        { "bucketName": "...", "bucketArn": "...", "region": "us-east-1" }

    Returns:
      {
        "bucketName": "...",
        "bucketArn": "...",
        "awsRegionUsed": "...",
        "bucketLocation": "us-east-1",
        "tags": {...}   // empty if none
      }
    """
    try:
        body = _try_get_json(req)

        bucket_name = (req.params.get("bucketName") or body.get("bucketName") or "").strip()
        bucket_arn = (req.params.get("bucketArn") or body.get("bucketArn") or "").strip()
        region = (req.params.get("region") or body.get("region") or os.getenv("AWS_REGION") or "us-east-1").strip()

        if not bucket_name and bucket_arn:
            bucket_name = _parse_s3_bucket_from_arn(bucket_arn) or ""

        if not bucket_name:
            return _json_http(
                {
                    "error": "Missing required parameter: bucketName (or bucketArn).",
                    "example_get": "GET ?bucketName=s3-example-bucket&region=us-east-1",
                    "example_post": {"bucketName": "s3-example-bucket", "region": "us-east-1"},
                },
                status_code=400,
            )

        # Ensure creds exist (fail fast with clear message)
        if not os.getenv("AWS_ACCESS_KEY_ID") or not os.getenv("AWS_SECRET_ACCESS_KEY"):
            return _json_http(
                {
                    "error": "AWS credentials missing in app settings.",
                    "requiredAppSettings": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
                    "optionalAppSettings": ["AWS_SESSION_TOKEN", "AWS_REGION"],
                },
                status_code=500,
            )

        s3 = _aws_client("s3", region=region)

        # 1) Residency signal: bucket location
        loc_resp = s3.get_bucket_location(Bucket=bucket_name)
        bucket_location = _normalize_s3_bucket_location(loc_resp.get("LocationConstraint"))

        # 2) Tags
        tags: Dict[str, str] = {}
        try:
            tag_resp = s3.get_bucket_tagging(Bucket=bucket_name)
            tagset = tag_resp.get("TagSet") or []
            tags = {str(t.get("Key")): str(t.get("Value", "")) for t in tagset if t.get("Key")}
        except ClientError as ce:
            code = (ce.response.get("Error") or {}).get("Code")
            # NoSuchTagSet means bucket has no tags — that's still a valid connectivity proof
            if code != "NoSuchTagSet":
                raise

        return _json_http(
            {
                "bucketName": bucket_name,
                "bucketArn": bucket_arn or f"arn:aws:s3:::{bucket_name}",
                "awsRegionUsed": region,
                "bucketLocation": bucket_location,
                "tags": tags,
            },
            status_code=200,
        )

    except Exception as e:
        logging.exception("Unhandled error in azure_residency_compliance_aws")
        return _json_http(
            {
                "error": "Unhandled exception",
                "details": str(e)[:2000],
            },
            status_code=500,
        )
